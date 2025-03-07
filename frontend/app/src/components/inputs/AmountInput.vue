<script setup lang="ts">
import IMask, { type InputMask } from 'imask';
import { useFrontendSettingsStore } from '@/store/settings/frontend';

defineOptions({
  inheritAttrs: false,
});

const model = defineModel<string>({ required: true });

const props = withDefaults(
  defineProps<{
    integer?: boolean;
    hideDetails?: boolean;
  }>(),
  {
    hideDetails: false,
    integer: false,
  },
);

const { integer } = toRefs(props);
const { decimalSeparator, thousandSeparator } = storeToRefs(useFrontendSettingsStore());

const textInput = ref<any>(null);
const imask = ref<InputMask<any> | null>(null);
const currentValue = ref<string>('');

onMounted(() => {
  const inputWrapper = get(textInput)!;
  const input = inputWrapper.$el.querySelector('input') as HTMLInputElement;

  const newImask = IMask(input, {
    mask: Number,
    radix: get(decimalSeparator),
    scale: get(integer) ? 0 : 100,
    thousandsSeparator: get(thousandSeparator),
  });

  newImask.on('accept', () => {
    const mask = get(imask);
    if (mask) {
      set(currentValue, mask?.value || '');
      set(model, mask?.unmaskedValue || '');
    }
  });

  const propValue = get(model);
  if (propValue) {
    newImask.unmaskedValue = propValue;
    set(currentValue, newImask.value);
  }

  set(imask, newImask);
});

watch(model, (value) => {
  const imaskVal = get(imask);
  if (imaskVal) {
    imaskVal.unmaskedValue = value;
    set(currentValue, imaskVal.value);
  }
});

function focus() {
  const inputWrapper = get(textInput) as any;
  if (inputWrapper)
    inputWrapper.focus();
}

function onFocus() {
  const inputWrapper = get(textInput)!;
  const input = inputWrapper.$el.querySelector('input') as HTMLInputElement;

  nextTick(() => {
    input.value = get(currentValue);
  });
}

function update(value: string) {
  if (!value) {
    set(model, '');
  }
}

defineExpose({
  focus,
});
</script>

<template>
  <RuiTextField
    ref="textInput"
    color="primary"
    :model-value="currentValue"
    v-bind="$attrs"
    :hide-details="hideDetails"
    @focus="onFocus()"
    @update:model-value="update($event)"
  >
    <template
      v-for="(_, name) in $slots"
      #[name]="scope"
    >
      <slot
        v-bind="scope"
        :name="name"
      />
    </template>
  </RuiTextField>
</template>
