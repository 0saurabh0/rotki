<script setup lang="ts">
import dayjs from 'dayjs';
import BigDialog from '@/components/dialogs/BigDialog.vue';
import RotkiLogo from '@/components/common/RotkiLogo.vue';
import AmountDisplay from '@/components/display/amount/AmountDisplay.vue';
import HashLink from '@/components/helper/HashLink.vue';
import AppImage from '@/components/common/AppImage.vue';
import { type WrapStatisticsResult, useWrapStatisticsApi } from '@/composables/api/statistics/wrap';
import { useExternalApiKeys } from '@/composables/settings/api-keys/external';
import { useTaskStore } from '@/store/tasks';
import { TaskType } from '@/types/task-type';
import { Section } from '@/types/status';
import { useCurrencies } from '@/types/currencies';
import WrappedCard from '@/components/wrapped/WrappedCard.vue';
import LocationDisplay from '@/components/history/LocationDisplay.vue';
import CounterpartyDisplay from '@/components/history/CounterpartyDisplay.vue';
import { useSupportedChains } from '@/composables/info/chains';
import ChainDisplay from '@/components/accounts/blockchain/ChainDisplay.vue';
import { logger } from '@/utils/logging';
import { sortDesc } from '@/utils/bignumbers';
import DateTimePicker from '@/components/inputs/DateTimePicker.vue';
import { convertFromTimestamp, convertToTimestamp } from '@/utils/date';
import { usePremium } from '@/composables/premium';
import ExternalLink from '@/components/helper/ExternalLink.vue';
import { useStatusUpdater } from '@/composables/status';
import { Routes } from '@/router/routes';
import WrappedScore from '@/components/wrapped/WrappedScore.vue';
import type { BigNumber } from '@rotki/common';

const display = defineModel<boolean>('display', { required: true });

const { t } = useI18n();
const premium = usePremium();
const { apiKey } = useExternalApiKeys(t);
const { isTaskRunning } = useTaskStore();
const { findCurrency } = useCurrencies();
const { fetchWrapStatistics } = useWrapStatisticsApi();
const { getChain } = useSupportedChains();

const gnosisPayKey = computed(() => apiKey('gnosis_pay'));
const showGnosisData = computed(() => get(premium) && get(gnosisPayKey));

const loading = ref(false);
const end = ref('');
const start = ref('');
const summary = ref<WrapStatisticsResult>();

const { isFirstLoad, loading: sectionLoading } = useStatusUpdater(Section.HISTORY_EVENT);
const eventTaskLoading = isTaskRunning(TaskType.TRANSACTIONS_DECODING);
const protocolCacheUpdatesLoading = isTaskRunning(TaskType.REFRESH_GENERAL_CACHE);
const onlineHistoryEventsLoading = isTaskRunning(TaskType.QUERY_ONLINE_EVENTS);

const refreshing = logicOr(sectionLoading, eventTaskLoading, onlineHistoryEventsLoading, protocolCacheUpdatesLoading);

const gnosisPayResult = computed(() => {
  const gnosisMaxPaymentsByCurrency = get(summary)?.gnosisMaxPaymentsByCurrency;
  if (!gnosisMaxPaymentsByCurrency) {
    return [];
  }

  const result: {
    amount: BigNumber;
    code: string;
    name: string;
    symbol: string;
  }[] = [];

  for (const payment of gnosisMaxPaymentsByCurrency) {
    try {
      const currency = findCurrency(payment.symbol);
      if (currency) {
        result.push({
          amount: payment.amount,
          code: payment.symbol,
          name: currency.name,
          symbol: currency.unicodeSymbol,
        });
      }
    }
    catch {
      result.push({
        amount: payment.amount,
        code: payment.symbol,
        name: payment.symbol,
        symbol: payment.symbol,
      });
    }
  }

  return result;
});

const currentYear = computed(() => new Date().getFullYear());

async function fetchData() {
  if (get(loading))
    return;

  try {
    const endVal = get(end);
    const startVal = get(start);

    if (!startVal || !endVal) {
      const range = getYearRange(get(currentYear));

      if (!startVal) {
        set(start, range.start);
      }
      if (!endVal) {
        set(end, range.end);
      }
    }

    set(loading, true);
    const response = await fetchWrapStatistics(
      {
        end: convertToTimestamp(get(end)),
        start: convertToTimestamp(get(start)),
      },
    );
    set(summary, response);
  }
  catch (error) {
    logger.error(error);
    set(summary, null);
  }
  finally {
    set(loading, false);
  }
}

function hasSectionData(data: Record<string, any> | Array<any> | undefined): boolean {
  if (!data)
    return false;
  if (Array.isArray(data))
    return data.length > 0;
  return Object.keys(data).length > 0;
}

function closeDialog() {
  set(display, false);
}

function formatDate(timestamp: number) {
  return dayjs(timestamp * 1000).format('dddd, MMMM D, YYYY');
}

function calculateFontSize(symbol: string) {
  const length = symbol.length;
  return `${1.8 - length * 0.4}em`;
}

const invalidRange = computed(
  () =>
    !!get(start)
    && !!get(end)
    && convertToTimestamp(get(start)) > convertToTimestamp(get(end)),
);

function getYearRange(year: number) {
  return {
    end: convertFromTimestamp(dayjs().year(year).endOf('year').unix()),
    start: convertFromTimestamp(dayjs().year(year).startOf('year').unix()),
  };
}

const isCurrentYear = computed(() => {
  const range = getYearRange(get(currentYear));
  return get(start) === range.start && get(end) === range.end;
});

watchImmediate(display, async (display) => {
  if (display) {
    await fetchData();
  }
});

watch(refreshing, async (curr, old) => {
  if (old && !curr) {
    await fetchData();
  }
});
</script>

<template>
  <BigDialog
    :display="display"
    :title="t('wrapped.title', { year: isCurrentYear ? currentYear : undefined })"
    :subtitle="t('wrapped.subtitle')"
    :loading="loading"
    :action-hidden="true"
    :secondary-action="t('common.actions.close')"
    max-width="800px"
    @cancel="closeDialog()"
    @close="closeDialog()"
  >
    <div
      class="flex flex-col gap-6 py-4 px-2"
    >
      <div class="py-8 w-full rounded-lg flex flex-col items-center bg-gradient-to-b from-transparent to-rui-primary/[0.05]">
        <RotkiLogo
          :size="3"
          class="mb-4"
        />
        <h2 class="text-4xl font-bold mb-2">
          {{ t('wrapped.title', { year: isCurrentYear ? currentYear : undefined }) }}
        </h2>
        <p class="text-xl text-rui-text-secondary">
          {{ t('wrapped.year_subtitle') }}
        </p>
      </div>

      <RuiAlert
        v-if="isFirstLoad()"
        type="info"
      >
        <i18n-t
          keypath="wrapped.history_events_nudge"
        >
          <template #link>
            <RouterLink
              :to="Routes.HISTORY_EVENTS"
            >
              <span class="underline">{{ t('transactions.title') }}</span>
            </RouterLink>
          </template>
        </i18n-t>
      </RuiAlert>

      <RuiAlert
        v-if="refreshing"
        type="info"
      >
        {{ t('wrapped.loading') }}
      </RuiAlert>
      <RuiAlert
        v-if="!premium"
        type="info"
        class="py-1 [&>div]:items-center"
      >
        <div class="flex justify-between items-center">
          {{ t('wrapped.premium_nudge') }}
          <ExternalLink
            :text="t('wrapped.get_rotki_premium')"
            variant="default"
            premium
            class="!flex [&_span]:!no-underline !px-3 !py-2"
            color="primary"
          >
            <template #append>
              <RuiIcon
                name="external-link-line"
                size="12"
              />
            </template>
          </ExternalLink>
        </div>
      </RuiAlert>

      <div class="flex gap-2 -mb-4 items-start">
        <div class="mt-2 mr-4 font-semibold">
          {{ t('wrapped.filter_by_date') }}
        </div>
        <DateTimePicker
          v-model="start"
          dense
          hide-timezone-selector
          :disabled="loading"
          class="flex-1"
          :label="t('generate.labels.start_date')"
          allow-empty
        />
        <DateTimePicker
          v-model="end"
          dense
          hide-timezone-selector
          :disabled="loading"
          class="flex-1"
          :label="t('generate.labels.end_date')"
        />
        <RuiButton
          color="primary"
          class="h-10"
          :disabled="refreshing"
          @click="fetchData()"
        >
          <template #prepend>
            <RuiIcon name="lu-send-horizontal" />
          </template>
          {{ t('wrapped.get_data') }}
        </RuiButton>
      </div>

      <RuiAlert
        v-if="invalidRange"
        type="error"
      >
        <template #title>
          {{ t('generate.validation.end_after_start') }}
        </template>
      </RuiAlert>

      <template v-if="loading">
        <WrappedCard
          v-for="i in 3"
          :key="i"
          :items="new Array(3).fill({})"
        >
          <template #header-icon>
            <RuiSkeletonLoader class="size-6" />
          </template>
          <template #header>
            <RuiSkeletonLoader class="w-60" />
          </template>
          <template #label>
            <RuiSkeletonLoader class="w-20" />
          </template>
          <template #value>
            <RuiSkeletonLoader class="w-20" />
          </template>
        </WrappedCard>
      </template>
      <div
        v-else-if="!summary"
        class="p-4 text-center"
      >
        {{ t('data_table.no_data') }}
      </div>
      <template v-else>
        <WrappedCard
          v-if="summary.ethOnGas"
          :items="[{ label: t('backend_mappings.events.type.gas_fee'), value: summary.ethOnGas }]"
        >
          <template #header-icon>
            <RuiIcon
              name="lu-fuel"
              class="text-rui-primary"
              size="12"
            />
          </template>
          <template #header>
            {{ t('wrapped.gas_spent_total') }}
          </template>
          <template #value="{ item }">
            <AmountDisplay
              :value="item.value"
              asset="ETH"
            />
          </template>
        </WrappedCard>

        <WrappedCard
          v-if="hasSectionData(summary.ethOnGasPerAddress)"
          :items="Object.entries(summary.ethOnGasPerAddress).sort((a, b) => sortDesc(a[1], b[1]))"
        >
          <template #header-icon>
            <RuiIcon
              name="lu-fuel"
              class="text-rui-primary"
              size="12"
            />
          </template>
          <template #header>
            {{ t('wrapped.gas_spent') }}
          </template>
          <template #label="{ item }">
            <HashLink
              class="bg-rui-grey-200 dark:bg-rui-grey-800 rounded-full pr-1"
              :text="item[0]"
            />
          </template>
          <template #value="{ item }">
            <AmountDisplay
              :value="item[1]"
              asset="ETH"
            />
          </template>
        </WrappedCard>

        <WrappedCard
          v-if="hasSectionData(summary.tradesByExchange)"
          :items="Object.entries(summary.tradesByExchange).sort((a, b) => sortDesc(a[1], b[1]))"
        >
          <template #header-icon>
            <RuiIcon
              name="exchange-line"
              class="text-rui-primary"
              size="12"
            />
          </template>
          <template #header>
            {{ t('wrapped.exchange_activity') }}
          </template>
          <template #label="{ item }">
            <LocationDisplay
              horizontal
              class="[&_span]:!text-rui-text"
              :identifier="item[0]"
            />
          </template>
          <template #value="{ item }">
            {{ item[1] }} {{ t('actions.trades.task.title') }}
          </template>
        </WrappedCard>

        <WrappedCard
          v-if="hasSectionData(summary.transactionsPerChain)"
          :items="Object.entries(summary.transactionsPerChain).sort((a, b) => sortDesc(a[1], b[1]))"
        >
          <template #header-icon>
            <RuiIcon
              name="git-branch-line"
              class="text-rui-primary"
              size="12"
            />
          </template>
          <template #header>
            {{ t('wrapped.transactions_by_chain') }}
          </template>
          <template #label="{ item }">
            <ChainDisplay
              dense
              :chain="getChain(item[0].toLowerCase())"
            />
          </template>
          <template #value="{ item }">
            {{ item[1] }} {{ t('explorers.tx') }}
          </template>
        </WrappedCard>

        <WrappedCard
          v-if="showGnosisData && hasSectionData(summary.gnosisMaxPaymentsByCurrency)"
          :items="gnosisPayResult"
        >
          <template #header-icon>
            <AppImage
              src="./assets/images/services/gnosispay.png"
              width="24px"
              height="24px"
              contain
            />
          </template>
          <template #header>
            {{ t('wrapped.gnosis_payments') }}
          </template>
          <template #label="{ item }">
            <div
              class="flex items-center justify-center gap-2 size-6 rounded-full bg-rui-grey-300 dark:bg-rui-grey-800"
              :style="{ fontSize: calculateFontSize(item.symbol) }"
            >
              {{ item.symbol }}
            </div>
            <div>
              {{ item.code }} - {{ item.name }}
            </div>
          </template>
          <template #value="{ item }">
            <AmountDisplay
              force-currency
              :value="item.amount"
            />
            {{ item.symbol }}
          </template>
        </WrappedCard>

        <WrappedCard
          v-if="hasSectionData(summary.topDaysByNumberOfTransactions)"
          :items="summary.topDaysByNumberOfTransactions.sort((a, b) => sortDesc(a.amount, b.amount))"
        >
          <template #header-icon>
            <RuiIcon
              name="lu-calendar-days"
              class="text-rui-primary"
              size="12"
            />
          </template>
          <template #header>
            {{ t('wrapped.top_days') }}
          </template>
          <template #label="{ item, index }">
            <span>{{ index + 1 }}.</span>
            {{ formatDate(item.timestamp) }}
          </template>
          <template #value="{ item }">
            {{ item.amount }} {{ t('explorers.tx') }}
          </template>
        </WrappedCard>

        <WrappedCard
          v-if="hasSectionData(summary.transactionsPerProtocol)"
          :items="summary.transactionsPerProtocol.sort((a, b) => sortDesc(a.transactions, b.transactions))"
        >
          <template #header-icon>
            <RuiIcon
              name="lu-blockchain"
              class="text-rui-primary"
              size="12"
            />
          </template>
          <template #header>
            {{ t('wrapped.protocol_activity') }}
          </template>
          <template #label="{ item, index }">
            <span>{{ index + 1 }}.</span>
            <CounterpartyDisplay :counterparty="item.protocol" />
          </template>
          <template #value="{ item }">
            {{ item.transactions }} {{ t('explorers.tx') }}
          </template>
        </WrappedCard>

        <WrappedScore
          :is-current-year="isCurrentYear"
          :score="summary.score"
        />
      </template>
    </div>
  </BigDialog>
</template>
