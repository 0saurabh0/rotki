import { type ComponentMountingOptions, type VueWrapper, mount } from '@vue/test-utils';
import { type Pinia, createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HistoryEventEntryType } from '@rotki/common';
import EthBlockEventForm from '@/components/history/events/forms/EthBlockEventForm.vue';
import { setupDayjs } from '@/utils/date';
import type { AssetMap } from '@/types/asset';
import type { EthBlockEvent } from '@/types/history/events';

vi.mock('@/store/balances/prices', () => ({
  useBalancePricesStore: vi.fn().mockReturnValue({
    getHistoricPrice: vi.fn(),
  }),
}));

describe('ethBlockEventForm.vue', () => {
  setupDayjs();
  let wrapper: VueWrapper<InstanceType<typeof EthBlockEventForm>>;
  let pinia: Pinia;

  const asset = {
    name: 'Ethereum',
    symbol: 'ETH',
    assetType: 'own chain',
    isCustomAsset: false,
  };

  const mapping: AssetMap = {
    assetCollections: {},
    assets: { [asset.symbol]: asset },
  };

  const groupHeader: EthBlockEvent = {
    identifier: 11336,
    entryType: HistoryEventEntryType.ETH_BLOCK_EVENT,
    eventIdentifier: 'BP1_444',
    sequenceIndex: 0,
    timestamp: 1697442021000,
    location: 'ethereum',
    asset: asset.symbol,
    balance: {
      amount: bigNumberify('100'),
      usdValue: bigNumberify('2000'),
    },
    eventType: 'staking',
    eventSubtype: 'mev reward',
    locationLabel: '0x106B62Fdd27B748CF2Da3BacAB91a2CaBaeE6dCa',
    notes:
      'Validator 12 produced block 444 with 100 ETH going to 0x106B62Fdd27B748CF2Da3BacAB91a2CaBaeE6dCa as the mev reward',
    validatorIndex: 122,
    blockNumber: 444,
  };

  beforeEach(() => {
    vi.useFakeTimers();
    pinia = createPinia();
    setActivePinia(pinia);
    vi.mocked(useAssetInfoApi().assetMapping).mockResolvedValue(mapping);
    vi.mocked(useBalancePricesStore().getHistoricPrice).mockResolvedValue(One);
  });

  afterEach(() => {
    wrapper.unmount();
  });

  const createWrapper = (options: ComponentMountingOptions<typeof EthBlockEventForm> = {}) =>
    mount(EthBlockEventForm, {
      global: {
        plugins: [pinia],
      },
      ...options,
    });

  describe('should prefill the fields based on the props', () => {
    it('no `groupHeader`, nor `editableItem` are passed', async () => {
      wrapper = createWrapper();
      await nextTick();

      expect((wrapper.find('[data-cy=blockNumber] input').element as HTMLInputElement).value).toBe('');

      expect((wrapper.find('[data-cy=validatorIndex] input').element as HTMLInputElement).value).toBe('');

      expect((wrapper.find('[data-cy=feeRecipient] .input-value').element as HTMLInputElement).value).toBe('');

      expect((wrapper.find('[data-cy=isMevReward] input').element as HTMLInputElement).checked).toBeFalsy();
    });

    it('`groupHeader` are passed', async () => {
      wrapper = createWrapper();
      await nextTick();
      await wrapper.setProps({ groupHeader });

      expect((wrapper.find('[data-cy=blockNumber] input').element as HTMLInputElement).value).toBe(
        groupHeader.blockNumber.toString(),
      );

      expect((wrapper.find('[data-cy=validatorIndex] input').element as HTMLInputElement).value).toBe(
        groupHeader.validatorIndex.toString(),
      );

      expect((wrapper.find('[data-cy=feeRecipient] .input-value').element as HTMLInputElement).value).toBe(
        groupHeader.locationLabel,
      );

      expect((wrapper.find('[data-cy=amount] input').element as HTMLInputElement).value).toBe('0');

      expect((wrapper.find('[data-cy=isMevReward] input').element as HTMLInputElement).checked).toBeFalsy();
    });

    it('`groupHeader` and `editableItem` are passed', async () => {
      wrapper = createWrapper();
      await nextTick();
      await wrapper.setProps({ groupHeader, editableItem: groupHeader });

      expect((wrapper.find('[data-cy=blockNumber] input').element as HTMLInputElement).value).toBe(
        groupHeader.blockNumber.toString(),
      );

      expect((wrapper.find('[data-cy=validatorIndex] input').element as HTMLInputElement).value).toBe(
        groupHeader.validatorIndex.toString(),
      );

      expect((wrapper.find('[data-cy=feeRecipient] .input-value').element as HTMLInputElement).value).toBe(
        groupHeader.locationLabel,
      );

      expect((wrapper.find('[data-cy=amount] input').element as HTMLInputElement).value).toBe(
        groupHeader.balance.amount.toString(),
      );

      expect((wrapper.find('[data-cy=isMevReward] input').element as HTMLInputElement).checked).toBeTruthy();
    });
  });
});
