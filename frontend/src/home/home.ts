const modules = import.meta.glob<string>("./assets/*.svg", {
  eager: true,
  query: "?url",
  import: "default",
});

export const art = Object.fromEntries(
  Object.entries(modules).map(([path, url]) => [
    path
      .split("/")
      .at(-1)!
      .replace(/\.svg$/, ""),
    url,
  ]),
) as Readonly<Record<string, string>>;

export const homeData = Object.freeze({
  displayName: "xxx",
  mainQuestion: 2,
  mainQuestionCount: 5,
  practiceCount: 3,
  priority: "讲清楚需求取舍的依据",
  priorityHint: "建议：补充需求优先级判断，同时说明暂缓的理由",
  completedInterviews: 6,
  practiceMinutes: 180,
});

export const destinations = Object.freeze({
  newInterview: "#/interview?tab=prepare",
  continueInterview: "#/interview/room",
  priorityPractice: "#/interview?tab=tasks&task=idempotency",
  allPractice: "#/interview?tab=tasks",
  history: "#/history",
});
