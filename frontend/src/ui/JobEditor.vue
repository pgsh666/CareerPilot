<script setup lang="ts">
import type { Job } from "../core/state";
const draft = defineModel<Job>({ required: true });
defineProps<{ error: string; busy?: boolean }>();
const emit = defineEmits<{ invalidate: []; parse: []; save: [] }>();
const sourceCount = () => Array.from(draft.value.source.replace(/\r\n?/g, '\n')).length;
</script>
<template>
  <div class="jd-compare">
    <section class="jd-source">
      <div class="jd-pane-head">
        <label :for="`jd-source-${draft.id}`">原始岗位描述</label
        ><span>{{ sourceCount() }} / 20,000 字符</span>
      </div>
      <textarea
        :id="`jd-source-${draft.id}`"
        v-model="draft.source"
        aria-label="粘贴岗位JD原文"
        spellcheck="false"
        :disabled="busy"
        @input="emit('invalidate')"
      />
      <p v-if="sourceCount() > 20000" class="inline-error" role="alert">超出 {{ sourceCount() - 20000 }} 个字符，请调整；完整输入已保留。</p>
      <div class="jd-source-actions">
        <button
          class="ui-button primary"
          :disabled="busy || !draft.source.trim() || sourceCount() > 20000"
          @click="emit('parse')"
        >
          {{ busy ? "处理中…" : draft.parsed ? "重新解析" : "解析 JD" }}
        </button>
      </div>
    </section>
    <section class="jd-analysis">
      <div class="jd-pane-head">解析结果</div>
      <fieldset class="jd-fieldset ui-scroll" :disabled="busy || !draft.parsed">
        <div class="field-pair">
          <label class="ui-field"
            ><span>岗位名称</span><input v-model="draft.name" /></label
          ><label class="ui-field"
            ><span>公司名称</span><input v-model="draft.company"
          /></label>
        </div>
        <div class="field-pair">
          <label class="ui-field"
            ><span>岗位类别</span
            ><select v-model="draft.role" aria-label="岗位类别">
              <option value="">选择岗位类别</option>
              <option
                v-for="value in [
                  '后端开发',
                  '前端开发',
                  '软件测试',
                  'AI 产品经理',
                  'AI 应用开发',
                ]"
                :key="value"
              >
                {{ value }}
              </option>
            </select></label
          ><label class="ui-field"
            ><span>岗位方向</span><input v-model="draft.direction"
          /></label>
        </div>
        <label class="ui-field"
          ><span>核心职责</span
          ><textarea v-model="draft.responsibilities" /></label
        ><label class="ui-field"
          ><span>明确要求 <small v-if="draft.extractedFields" aria-hidden="true">{{ draft.requirements === draft.extractedFields.requirements ? '原文摘录' : '用户补充 / 修改' }}</small></span><textarea v-model="draft.requirements" aria-label="明确要求" />
        </label>
        <details class="jd-inference">
          <summary>推断与缺项</summary>
          <label class="ui-field"
            ><span>待确认内容</span
            ><textarea v-model="draft.inference" /></label
          ><label class="checkbox"
            ><input
              v-model="draft.useInference"
              type="checkbox"
            />确认将以上推断用于本次面试</label
          >
        </details>
      </fieldset>
      <div class="jd-analysis-actions">
        <p class="inline-error" role="status">{{ error }}</p>
        <button
          class="ui-button primary"
          :disabled="busy || !draft.parsed || sourceCount() > 20000"
          @click="emit('save')"
        >
          确认并保存
        </button>
      </div>
    </section>
  </div>
</template>
<style scoped>
.jd-compare {
  display: grid;
  grid-template-columns: minmax(0, 44fr) minmax(0, 56fr);
  gap: 22px;
  padding: 0 24px 20px;
  flex: 1;
  min-height: 0;
}
.jd-source,
.jd-analysis {
  border: 1px solid #e2e8f2;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.jd-pane-head {
  min-height: 40px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  border-bottom: 1px solid #edf0f6;
  flex: none;
}
.jd-pane-head > span {
  color: #8b98ad;
  font-size: 0.8em;
  font-weight: 400;
}
.jd-source > textarea {
  flex: 1;
  min-height: 0;
  margin: 12px 16px 0;
  width: calc(100% - 32px);
  border: 1px solid #dee5f0;
  border-radius: 8px;
  padding: 14px;
  line-height: 1.8;
  resize: none;
  background: #fff;
}
.jd-source-actions {
  padding: 12px 16px;
  display: flex;
  justify-content: flex-end;
  flex: none;
}
.jd-fieldset {
  flex: 1;
  padding: 12px 16px;
  font-size: 0.88em;
}
.jd-fieldset:disabled {
  opacity: 0.45;
}
.jd-fieldset .ui-field {
  gap: 5px;
  margin-bottom: 12px;
}
.jd-fieldset .ui-field textarea {
  min-height: 62px;
}
.jd-inference {
  border-top: 1px solid #edf0f6;
  padding-top: 10px;
  color: #7a8ba6;
}
.jd-inference summary {
  cursor: pointer;
  margin-bottom: 10px;
}
.jd-analysis-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 10px 16px;
  flex: none;
}
.jd-analysis-actions .inline-error {
  flex: 1;
  font-size: 0.76em;
}
.jd-analysis-actions .ui-button {
  flex: none;
}

@media (max-width: 1200px) {
  .jd-compare {
    gap: 16px;
    padding: 0 18px 18px;
  }
  .jd-fieldset {
    padding: 12px;
  }
  .jd-analysis-actions {
    padding: 8px 12px;
  }
  .jd-analysis-actions .ui-button {
    padding: 0 12px;
  }
}
</style>
