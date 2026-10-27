<script setup lang="ts">
import type { Feedback } from "../core/training";
defineProps<{ feedback?: Feedback; pending?: string }>();
</script>
<template>
  <div class="evidence-grid">
    <section v-for="kind in ['strengths', 'missing'] as const" :key="kind">
      <h3>{{ kind === "strengths" ? "已体现" : "仍需补充" }}</h3>
      <template v-if="feedback"
        ><article v-for="e in feedback[kind]" :key="e.answer_id + e.quote">
          <blockquote>{{ e.quote }}</blockquote>
          <p>{{ e.comment }}</p>
        </article>
        <p v-if="!feedback[kind].length" class="muted-copy">
          本次未指出该项内容。
        </p></template
      >
      <p v-else class="muted-copy">{{ pending || "反馈待生成" }}</p>
    </section>
  </div>
  <p v-if="feedback?.comparison" class="evidence-comparison">
    {{ feedback.comparison }}
  </p>
</template>
<style scoped>
.evidence-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin: 20px 0;
}
.evidence-grid section {
  border: 1px solid #e4eaf4;
  border-radius: 12px;
  padding: 18px;
}
h3 {
  font-size: 1em;
  color: #667895;
  margin-bottom: 12px;
}
article + article {
  margin-top: 14px;
}
blockquote {
  margin: 0 0 8px;
  padding: 10px 14px;
  border-left: 2px solid #adc3ec;
  background: #f7f9fd;
  white-space: pre-wrap;
}
p,
blockquote {
  font-size: 0.9em;
  line-height: 1.8;
  color: #667895;
}
.evidence-comparison {
  margin-top: 16px;
}
</style>
