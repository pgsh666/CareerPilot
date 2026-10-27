import { createRouter, createWebHashHistory } from "vue-router";
import HomePage from "./home/HomePage.vue";
import ResumesPage from "./pages/ResumesPage.vue";
import InterviewPage from "./pages/InterviewPage.vue";
import RoomPage from "./pages/RoomPage.vue";
import HistoryPage from "./pages/HistoryPage.vue";
import ResultPage from "./pages/ResultPage.vue";
import SettingsPage from "./pages/SettingsPage.vue";
import AdminPage from "./pages/AdminPage.vue";
import LoginPage from "./pages/LoginPage.vue";
import { state } from "./core/state";
import { restoreSession } from "./core/auth";
import { loadMaterials } from "./core/materials";
import { loadTrainingSummary } from "./core/training";
import {
  navigationLabels,
  previousNavigation,
  navigationDirection,
} from "./ui/navigationMotion";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/login" },
    {
      path: "/home",
      component: HomePage,
      meta: { title: "首页", nav: "首页" },
    },
    { path: "/login", component: LoginPage, meta: { title: "登录" } },
    {
      path: "/resumes",
      component: ResumesPage,
      meta: { title: "我的简历", nav: "简历" },
    },
    {
      path: "/interview",
      component: InterviewPage,
      meta: { title: "面试", nav: "面试" },
    },
    {
      path: "/interview/room",
      component: RoomPage,
      meta: { title: "模拟面试", nav: "面试" },
    },
    {
      path: "/history",
      component: HistoryPage,
      meta: { title: "历史记录", nav: "历史" },
    },
    {
      path: "/reports/:id",
      component: ResultPage,
      meta: { title: "面试报告", nav: "历史", kind: "report" },
    },
    {
      path: "/practice/:id",
      component: ResultPage,
      meta: { title: "复练详情", nav: "历史", kind: "practice" },
    },
    {
      path: "/settings",
      component: SettingsPage,
      meta: { title: "账号管理", nav: "设置" },
    },
    {
      path: "/admin",
      component: AdminPage,
      meta: { title: "管理中心", nav: "设置", admin: true },
    },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
router.beforeEach(async (to) => {
  await restoreSession();
  if (!state.signedIn && to.path !== "/login")
    return { path: "/login", query: { redirect: to.fullPath } };
  if (to.path === "/settings" && state.account.role === "admin")
    return "/admin";
  if (to.meta.admin && state.account.role !== "admin") return "/settings";
  if (state.signedIn && ["/resumes", "/interview"].includes(to.path)) {
    await loadMaterials();
    if (!state.signedIn) return { path: "/login", query: { form: "login" } };
  }
  if (state.signedIn && ["/home", "/interview", "/interview/room"].includes(to.path))
    await loadTrainingSummary();
  document.title = `${String(to.meta.title || "CareerPilot")} · CareerPilot`;
});
function recheckRoute() {
  if (!state.signedIn && router.currentRoute.value.path !== "/login")
    void router.replace({
      path: "/login",
      query: {
        form: "login",
        redirect: router.currentRoute.value.fullPath,
      },
    });
  else if (
    router.currentRoute.value.meta.admin &&
    state.account.role !== "admin"
  )
    void router.replace("/settings");
}
window.addEventListener("careerpilot:auth-lost", recheckRoute);
window.addEventListener("careerpilot:auth-rechecked", recheckRoute);
router.afterEach((to, from, failure) => {
  if (failure) return;
  const previous = navigationLabels.indexOf(
    String(from.meta.nav || to.meta.nav),
  );
  previousNavigation.value = Math.max(0, previous);
  const next = navigationLabels.indexOf(String(to.meta.nav));
  navigationDirection.value =
    next === previous
      ? to.path.split("/").length < from.path.split("/").length
        ? -1
        : 1
      : next > previous
        ? 1
        : -1;
});
