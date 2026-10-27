<script setup lang="ts">
import { ref } from "vue";
import UiIcon from "./UiIcon.vue";
import UiModal from "./UiModal.vue";
defineProps<{
  trend?: {
    version: string;
    sampleCount: number;
    dimensions: { id: string; name: string }[];
    group: { title: string; direction: string; jdVersion: number } | null;
  } | null;
}>();
const open = ref(false);
</script>
<template>
  <span class="score-help"
    >评分说明<button
      class="icon-button"
      aria-label="查看评分说明"
      :aria-expanded="open"
      @click="open = true"
    >
      <UiIcon name="help" :size="18" /></button
  ></span>
  <UiModal :open="open" wide title="评分说明" @close="open = false">
    <div class="score-explanation">
      <h3>分数怎样计算</h3>
      <p>
        各维度按0—4档评价，对应0、25、50、75、100分。主问题及其追问作为一个题组综合评价；同一维度在不同题组中的有效分数等权平均。
      </p>
      <p>
        通用维度占40%：回答相关性15%、逻辑表达10%、回答依据与职责说明15%；岗位专项三项各占20%，合计60%。无评分依据显示N/A，不补零、不重新分配权重。
      </p>
      <h3>什么时候显示综合分</h3>
      <p>
        评价已完成、至少3个不同题组有评分依据、六项维度均有有效分数且证据覆盖率达到80%，才按固定权重显示综合分。证据覆盖率按各维度实际证据占原定考察范围的比例加权计算；跳过或未答题组保留在分母中。
      </p>
      <h3>趋势图怎样比较</h3>
      <p>
        只比较同岗位及方向、同JD版本、同评分版本、正常完成且综合分有效的面试。系统自动选择当前筛选条件下有合格样本的最新评分版本；没有样本时使用当前启用版本，版本之间不会混成一条曲线。
      </p>
      <p>
        趋势显示岗位专项代表维度和逻辑表达两条曲线；一个样本显示散点，多个样本连线。复练和提前结束的面试不纳入曲线。
      </p>
      <div v-if="trend" class="score-selection">
        <p>
          本次自动采用：<code>{{ trend.version }}</code> ·
          {{ trend.sampleCount }}场可比面试
        </p>
        <p v-if="trend.group">
          比较范围：{{ trend.group.title }} · {{ trend.group.direction }} · JD
          v{{ trend.group.jdVersion }}
        </p>
        <p
          v-for="(dimension, index) in trend.dimensions"
          :key="dimension.id"
          :style="{ color: index === 0 ? '#587fe5' : '#3aa88b' }"
        >
          ● {{ dimension.name }}
        </p>
      </div>
    </div>
    <template #footer
      ><button class="ui-button primary" @click="open = false">
        知道了
      </button></template
    >
  </UiModal>
</template>
<style scoped>
.score-help {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #8292ad;
  font-size: 12px;
  white-space: nowrap;
}
.score-help .icon-button {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  color: #8292ad;
}
.score-explanation {
  color: #61738e;
  font-size: 14px;
  line-height: 1.8;
}
.score-explanation h3 {
  color: #344764;
  font-size: 15px;
  margin: 16px 0 6px;
}
.score-explanation h3:first-child {
  margin-top: 0;
}
.score-explanation p {
  margin: 8px 0;
}
.score-selection {
  border-top: 1px solid #dce3ee;
  margin-top: 16px;
  padding-top: 8px;
}
.score-selection code {
  overflow-wrap: anywhere;
}
</style>
