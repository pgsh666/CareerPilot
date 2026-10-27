<script setup lang="ts">
import { computed } from "vue";
import UiIcon from "./UiIcon.vue";
const props = defineProps<{
  total: number;
  size: number;
  modelValue: number;
}>();
const emit = defineEmits<{ "update:modelValue": [value: number] }>();
const count = computed(() => Math.max(1, Math.ceil(props.total / props.size)));
const pages = computed(() => {
  const first = Math.max(1, Math.min(props.modelValue - 2, count.value - 4));
  return Array.from({ length: Math.min(5, count.value) }, (_, i) => first + i);
});
</script>
<template>
  <div class="pagination">
    <button
      aria-label="上一页"
      :disabled="modelValue <= 1"
      @click="emit('update:modelValue', modelValue - 1)"
    >
      <UiIcon name="prev" :size="16" /></button
    ><button
      v-for="n in pages"
      :key="n"
      :class="{ active: n === modelValue }"
      :aria-label="`第${n}页`"
      :aria-current="n === modelValue ? 'page' : undefined"
      @click="emit('update:modelValue', n)"
    >
      {{ n }}</button
    ><button
      aria-label="下一页"
      :disabled="modelValue >= count"
      @click="emit('update:modelValue', modelValue + 1)"
    >
      <UiIcon name="next" :size="16" />
    </button>
  </div>
</template>
