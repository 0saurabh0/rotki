import base64
import hashlib
import hmac
import json
import logging
import operator
from collections.abc import Sequence
from json.decoder import JSONDecodeError
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode

import gevent
import requests

from rotkehlchen.accounting.structures.balance import Balance
from rotkehlchen.assets.converters import asset_from_poloniex
from rotkehlchen.constants import ZERO
from rotkehlchen.constants.assets import A_LEND
from rotkehlchen.data_import.utils import maybe_set_transaction_extra_data
from rotkehlchen.db.settings import CachedSettings
from rotkehlchen.errors.asset import UnknownAsset, UnprocessableTradePair, UnsupportedAsset
from rotkehlchen.errors.misc import RemoteError
from rotkehlchen.errors.serialization import DeserializationError
from rotkehlchen.exchanges.data_structures import MarginPosition, Trade, TradeType
from rotkehlchen.exchanges.exchange import ExchangeInterface, ExchangeQueryBalances
from rotkehlchen.exchanges.utils import deserialize_asset_movement_address, get_key_if_has_val
from rotkehlchen.history.deserialization import deserialize_price
from rotkehlchen.history.events.structures.asset_movement import (
    AssetMovement,
    create_asset_movement_with_fee,
)
from rotkehlchen.history.events.structures.base import HistoryBaseEntry
from rotkehlchen.history.events.structures.types import HistoryEventType
from rotkehlchen.inquirer import Inquirer
from rotkehlchen.logging import RotkehlchenLogsAdapter
from rotkehlchen.serialization.deserialize import (
    deserialize_asset_amount,
    deserialize_asset_amount_force_positive,
    deserialize_fee,
    deserialize_timestamp,
    deserialize_timestamp_from_intms,
    get_pair_position_str,
)
from rotkehlchen.types import (
    ApiKey,
    ApiSecret,
    ExchangeAuthCredentials,
    Fee,
    Location,
    Timestamp,
    TimestampMS,
)
from rotkehlchen.user_messages import MessagesAggregator
from rotkehlchen.utils.misc import ts_now_in_ms, ts_sec_to_ms
from rotkehlchen.utils.mixins.cacheable import cache_response_timewise
from rotkehlchen.utils.mixins.lockable import protect_with_lock

if TYPE_CHECKING:
    from rotkehlchen.assets.asset import AssetWithOracles
    from rotkehlchen.db.dbhandler import DBHandler

logger = logging.getLogger(__name__)
log = RotkehlchenLogsAdapter(logger)


PUBLIC_API_ENDPOINTS = ('/currencies',)


def trade_from_poloniex(poloniex_trade: dict[str, Any]) -> Trade:
    """Turn a poloniex trade returned from poloniex trade history to our common trade
    history format

    Throws:
        - UnsupportedAsset due to asset_from_poloniex()
        - DeserializationError due to the data being in unexpected format
        - UnprocessableTradePair due to the pair data being in an unexpected format
    """
    try:
        pair = poloniex_trade['symbol']
        trade_type = TradeType.deserialize(poloniex_trade['side'])
        # quantity is the base units of the trade
        amount = deserialize_asset_amount(poloniex_trade['quantity'])
        rate = deserialize_price(poloniex_trade['price'])
        fee = deserialize_fee(poloniex_trade['feeAmount'])
        fee_currency = asset_from_poloniex(poloniex_trade['feeCurrency'])
        base_currency = asset_from_poloniex(get_pair_position_str(pair, 'first'))
        quote_currency = asset_from_poloniex(get_pair_position_str(pair, 'second'))
        timestamp = deserialize_timestamp_from_intms(poloniex_trade['createTime'])
    except KeyError as e:
        raise DeserializationError(
            f'Poloniex trade deserialization error. Missing key entry for {e!s} in trade dict',
        ) from e

    log.debug(
        'Processing poloniex Trade',
        timestamp=timestamp,
        order_type=trade_type,
        base_currency=base_currency,
        quote_currency=quote_currency,
        amount=amount,
        fee=fee,
        rate=rate,
    )

    return Trade(
        timestamp=timestamp,
        location=Location.POLONIEX,
        # Since in Poloniex the base currency is the cost currency, iow in poloniex
        # for BTC_ETH we buy ETH with BTC and sell ETH for BTC, we need to turn it
        # into the Rotkehlchen way which is following the base/quote approach.
        base_asset=base_currency,
        quote_asset=quote_currency,
        trade_type=trade_type,
        amount=amount,
        rate=rate,
        fee=fee,
        fee_currency=fee_currency,
        link=str(poloniex_trade['id']),
    )


class Poloniex(ExchangeInterface):

    def __init__(
            self,
            name: str,
            api_key: ApiKey,
            secret: ApiSecret,
            database: 'DBHandler',
            msg_aggregator: MessagesAggregator,
    ):
        super().__init__(
            name=name,
            location=Location.POLONIEX,
            api_key=api_key,
            secret=secret,
            database=database,
            msg_aggregator=msg_aggregator,
        )

        self.uri = 'https://api.poloniex.com'
        self.session.headers.update({'key': self.api_key})

    def first_connection(self) -> None:
        if self.first_connection_made:
            return

        self.first_connection_made = True

    def edit_exchange_credentials(self, credentials: ExchangeAuthCredentials) -> bool:
        changed = super().edit_exchange_credentials(credentials)
        if credentials.api_key is not None:
            self.session.headers.update({'key': self.api_key})

        return changed

    def validate_api_key(self) -> tuple[bool, str]:
        try:
            self.return_fee_info()
        except RemoteError as e:
            error = str(e)
            if 'Invalid API key' in error:
                return False, 'Provided API Key or secret is invalid'
            # else reraise
            raise
        return True, ''

    def api_query_dict(self, command: str, req: dict | None = None) -> dict:
        result = self._api_query(command, req)
        if not isinstance(result, dict):
            raise RemoteError(
                f'Poloniex query for {command} did not return a dict result. Result: {result}',
            )
        return result

    def api_query_list(self, command: str, req: dict | None = None) -> list:
        result = self._api_query(command, req)
        if not isinstance(result, list):
            raise RemoteError(
                f'Poloniex query for {command} did not return a list result. Result: {result}',
            )
        return result

    def _create_sign(
            self,
            timestamp: TimestampMS,
            params: dict[str, Any],
            method: Literal['GET'],
            path: str,
    ) -> str:
        """Method taken from here:
         https://github.com/poloniex/polo-spot-sdk/tree/BRANCH_SANDBOX/signature_demo
        """
        if method == 'GET':
            params.update({'signTimestamp': timestamp})
            sorted_params = sorted(params.items(), key=operator.itemgetter(0), reverse=False)
            encode_params = urlencode(sorted_params)
            del params['signTimestamp']
        else:
            request_body = json.dumps(params)  # type: ignore
            encode_params = f'requestBody={request_body}&signTimestamp={timestamp}'
        sign_params_first = [method, path, encode_params]
        sign_params_second = '\n'.join(sign_params_first)
        sign_params = sign_params_second.encode(encoding='UTF8')
        digest = hmac.new(self.secret, sign_params, digestmod=hashlib.sha256).digest()
        signature = base64.b64encode(digest)
        return signature.decode()

    def _single_query(self, path: str, req: dict[str, Any]) -> requests.Response | None:
        """A single api query for poloniex

        Returns the response if all went well or None if a recoverable poloniex
        error occurred such as a 504.

        Can raise:
         - RemoteError if there is a problem with the response
         - ConnectionError if there is a problem connecting to poloniex.
        """
        if path in PUBLIC_API_ENDPOINTS:
            log.debug(f'Querying poloniex for {path}')
            response = self.session.get(self.uri + path, timeout=CachedSettings().get_timeout_tuple())  # noqa: E501
        else:
            timestamp = ts_now_in_ms()
            sign = self._create_sign(timestamp=timestamp, params=req, method='GET', path=path)
            self.session.headers.update({
                'signTimestamp': str(timestamp),
                'signature': sign,
            })
            params = urlencode(req)
            if params == '':
                url = f'{self.uri}{path}'
            else:
                url = f'{self.uri}{path}?{params}'
            response = self.session.get(url, params={}, timeout=CachedSettings().get_timeout_tuple())  # noqa: E501

        if response.status_code == 504:
            # backoff and repeat
            return None
        if response.status_code != 200:
            raise RemoteError(
                f'Poloniex query responded with error status code: {response.status_code}'
                f' and text: {response.text}',
            )

        # else all is good
        return response

    def _api_query(self, command: str, req: dict | None = None) -> dict | list:
        """An api query to poloniex. May make multiple requests

        Can raise:
         - RemoteError if there is a problem reaching poloniex or with the returned response
        """
        if req is None:
            req = {}
        log.debug(
            'Poloniex API query',
            command=command,
            post_data=req,
        )

        tries = CachedSettings().get_query_retry_limit()
        while tries >= 0:
            try:
                response = self._single_query(command, req)
            except requests.exceptions.RequestException as e:
                raise RemoteError(f'Poloniex API request failed due to {e!s}') from e

            if response is None and tries >= 1:
                backoff_seconds = 20 / tries
                log.debug(
                    f'Got a recoverable poloniex error. '
                    f'Backing off for {backoff_seconds}',
                )
                gevent.sleep(backoff_seconds)
                tries -= 1
            else:
                break

        if response is None:
            raise RemoteError(
                f'Got a recoverable poloniex error and did not manage to get a '
                f'request through even after {CachedSettings().get_query_retry_limit()} '
                f'incremental backoff retries',
            )

        result: dict | list
        try:
            result = response.json()
        except JSONDecodeError as e:
            raise RemoteError(f'Poloniex returned invalid JSON response: {response.text}') from e

        if isinstance(result, dict) and 'error' in result:
            raise RemoteError(
                'Poloniex query for "{}" returned error: {}'.format(
                    command,
                    result['error'],
                ))

        return result

    def return_fee_info(self) -> dict:
        return self.api_query_dict('/feeinfo')

    def return_trade_history(
            self,
            start: Timestamp,
            end: Timestamp,
    ) -> list[dict[str, Any]]:
        """Returns poloniex trade history"""
        limit = 100
        data: list[dict[str, Any]] = []
        start_ms = start * 1000
        end_ms = end * 1000
        while True:
            new_data = self.api_query_list('/trades', {
                'startTime': start_ms,
                'endTime': end_ms,
                'limit': limit,
            })
            results_length = len(new_data)
            if data == [] and results_length < limit:
                return new_data  # simple case - only one query needed

            latest_ts_ms = start_ms
            # add results to data and prepare for next query
            existing_ids = {x['id'] for x in data}
            for trade in new_data:
                try:
                    timestamp_ms = trade['createTime']
                    latest_ts_ms = max(latest_ts_ms, timestamp_ms)
                    # since we query again from last ts seen make sure no duplicates make it in
                    if trade['id'] not in existing_ids:
                        data.append(trade)
                except (DeserializationError, KeyError) as e:
                    msg = str(e)
                    if isinstance(e, KeyError):
                        msg = f'Missing key entry for {msg}.'
                    self.msg_aggregator.add_warning(
                        'Error deserializing a poloniex trade. Check the logs for details',
                    )
                    log.error(
                        'Error deserializing poloniex trade',
                        trade=trade,
                        error=msg,
                    )
                    continue

            if results_length < limit:
                break  # last query has less than limit. We are done.

            # otherwise we query again from the last ts seen in the last result
            start_ms = latest_ts_ms
            continue

        return data

    # ---- General exchanges interface ----
    @protect_with_lock()
    @cache_response_timewise()
    def query_balances(self) -> ExchangeQueryBalances:
        try:
            resp = self.api_query_list('/accounts/balances')
        except RemoteError as e:
            msg = (
                'Poloniex API request failed. Could not reach poloniex due '
                f'to {e}'
            )
            log.error(msg)
            return None, msg

        assets_balance: dict[AssetWithOracles, Balance] = {}
        for account_info in resp:
            try:
                balances = account_info['balances']
            except KeyError:
                self.msg_aggregator.add_error('Could not find balances key in the balances response')  # noqa: E501
                continue

            for balance_entry in balances:
                try:
                    available = deserialize_asset_amount(balance_entry['available'])
                    on_orders = deserialize_asset_amount(balance_entry['hold'])
                    poloniex_asset = balance_entry['currency']
                except (DeserializationError, KeyError) as e:
                    msg = str(e)
                    if isinstance(e, KeyError):
                        msg = f'Missing key entry for {msg}.'
                    self.msg_aggregator.add_error(
                        f'Could not deserialize amount from poloniex due to '
                        f'{msg}. Ignoring its balance query.',
                    )
                    continue

                if available != ZERO or on_orders != ZERO:
                    try:
                        asset = asset_from_poloniex(poloniex_asset)
                    except UnsupportedAsset as e:
                        self.msg_aggregator.add_warning(
                            f'Found unsupported poloniex asset {e.identifier}. '
                            f'Ignoring its balance query.',
                        )
                        continue
                    except UnknownAsset as e:
                        self.send_unknown_asset_message(
                            asset_identifier=e.identifier,
                            details='balance query',
                        )
                        continue
                    except DeserializationError:
                        log.error(
                            f'Unexpected poloniex asset type. Expected string '
                            f' but got {type(poloniex_asset)}',
                        )
                        self.msg_aggregator.add_error(
                            'Found poloniex asset entry with non-string type. '
                            'Ignoring its balance query.',
                        )
                        continue

                    if asset == A_LEND:  # poloniex mistakenly returns LEND balances
                        continue  # https://github.com/rotki/rotki/issues/2530

                    try:
                        usd_price = Inquirer.find_usd_price(asset=asset)
                    except RemoteError as e:
                        self.msg_aggregator.add_error(
                            f'Error processing poloniex balance entry due to inability to '
                            f'query USD price: {e!s}. Skipping balance entry',
                        )
                        continue

                    amount = available + on_orders
                    usd_value = amount * usd_price
                    assets_balance[asset] = Balance(
                        amount=amount,
                        usd_value=usd_value,
                    )
                    log.debug(
                        'Poloniex balance query',
                        currency=asset,
                        amount=amount,
                        usd_value=usd_value,
                    )

        return assets_balance, ''

    def query_online_trade_history(
            self,
            start_ts: Timestamp,
            end_ts: Timestamp,
    ) -> tuple[list[Trade], tuple[Timestamp, Timestamp]]:
        raw_data = self.return_trade_history(
            start=start_ts,
            end=end_ts,
        )
        log.debug('Poloniex trade history query', results_num=len(raw_data))
        our_trades = []
        for trade in raw_data:
            account_type = trade.get('accountType', None)
            try:
                if account_type == 'SPOT':
                    timestamp = deserialize_timestamp_from_intms(trade['createTime'])
                    if timestamp < start_ts or timestamp > end_ts:
                        continue
                    our_trades.append(trade_from_poloniex(trade))
                else:
                    log.warning(
                        f'Error deserializing a poloniex trade. Unknown trade '
                        f'accountType {account_type} found.',
                    )
                    continue
            except UnsupportedAsset as e:
                self.msg_aggregator.add_warning(
                    f'Found poloniex trade with unsupported asset'
                    f' {e.identifier}. Ignoring it.',
                )
                continue
            except UnknownAsset as e:
                self.send_unknown_asset_message(
                    asset_identifier=e.identifier,
                    details='trade',
                )
                continue
            except (UnprocessableTradePair, DeserializationError) as e:
                self.msg_aggregator.add_error(
                    'Error deserializing a poloniex trade. Check the logs '
                    'and open a bug report.',
                )
                log.error(
                    'Error deserializing poloniex trade',
                    trade=trade,
                    error=str(e),
                )
                continue

        return our_trades, (start_ts, end_ts)

    def _deserialize_asset_movement(
            self,
            movement_type: Literal[HistoryEventType.DEPOSIT, HistoryEventType.WITHDRAWAL],
            movement_data: dict[str, Any],
    ) -> list[AssetMovement]:
        """Processes a single deposit/withdrawal from polo and deserializes it

        Can log error/warning and return None if something went wrong at deserialization
        """
        try:
            if movement_type == HistoryEventType.DEPOSIT:
                fee = Fee(ZERO)
                uid_key = 'depositNumber'
                transaction_id = get_key_if_has_val(movement_data, 'txid')
            else:
                fee = deserialize_fee(movement_data['fee'])
                uid_key = 'withdrawalRequestsId'
                split = movement_data['status'].split(':')
                if len(split) != 2:
                    transaction_id = None
                else:
                    transaction_id = split[1].lstrip()
                    if transaction_id == '':
                        transaction_id = None

            asset = asset_from_poloniex(movement_data['currency'])
            return create_asset_movement_with_fee(
                location=self.location,
                location_label=self.name,
                event_type=movement_type,
                timestamp=ts_sec_to_ms(deserialize_timestamp(movement_data['timestamp'])),
                asset=asset,
                amount=deserialize_asset_amount_force_positive(movement_data['amount']),
                fee_asset=asset,
                fee=fee,
                unique_id=f'{movement_type.serialize()}_{movement_data[uid_key]!s}',  # movement_data[uid_key] is only unique within the same event type  # noqa: E501
                extra_data=maybe_set_transaction_extra_data(
                    address=deserialize_asset_movement_address(movement_data, 'address', asset),
                    transaction_id=transaction_id,
                ),
            )
        except UnsupportedAsset as e:
            self.msg_aggregator.add_warning(
                f'Found {movement_type!s} of unsupported poloniex asset '
                f'{e.identifier}. Ignoring it.',
            )
        except UnknownAsset as e:
            self.send_unknown_asset_message(
                asset_identifier=e.identifier,
                details='asset movement',
            )
        except (DeserializationError, KeyError) as e:
            msg = str(e)
            if isinstance(e, KeyError):
                msg = f'Missing key entry for {msg}.'
            self.msg_aggregator.add_error(
                'Unexpected data encountered during deserialization of a poloniex '
                'asset movement. Check logs for details and open a bug report.',
            )
            log.error(
                f'Unexpected data encountered during deserialization of poloniex '
                f'{movement_type!s}: {movement_data}. Error was: {msg}',
            )

        return []

    def query_online_history_events(
            self,
            start_ts: Timestamp,
            end_ts: Timestamp,
    ) -> Sequence[HistoryBaseEntry]:
        result = self.api_query_dict(
            '/wallets/activity',
            {'start': start_ts, 'end': end_ts},
        )
        log.debug(
            'Poloniex deposits/withdrawal query',
            results_num=len(result['withdrawals']) + len(result['deposits']),
        )

        movements = []
        for withdrawal in result['withdrawals']:
            movements.extend(self._deserialize_asset_movement(
                movement_type=HistoryEventType.WITHDRAWAL,
                movement_data=withdrawal,
            ))

        for deposit in result['deposits']:
            movements.extend(self._deserialize_asset_movement(
                movement_type=HistoryEventType.DEPOSIT,
                movement_data=deposit,
            ))

        return movements

    def query_online_margin_history(
            self,
            start_ts: Timestamp,  # pylint: disable=unused-argument
            end_ts: Timestamp,
    ) -> list[MarginPosition]:
        return []  # noop for poloniex
