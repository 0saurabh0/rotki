<script setup lang="ts">
import { useLinks } from '@/composables/links';
import MenuTooltipButton from '@/components/helper/MenuTooltipButton.vue';

const { href, onLinkClick } = useLinks();
const { t } = useI18n();
</script>

<template>
  <RuiBadge
    placement="top"
    offset-y="12"
    offset-x="-10"
    size="sm"
  >
    <template #icon>
      <RuiIcon
        name="lock-line"
        size="10"
      />
    </template>
    <MenuTooltipButton
      :tooltip="t('theme_switch_lock.tooltip')"
      :href="href"
      @click="onLinkClick()"
    >
      <RuiIcon name="sun-line" />
    </MenuTooltipButton>
  </RuiBadge>
</template>
