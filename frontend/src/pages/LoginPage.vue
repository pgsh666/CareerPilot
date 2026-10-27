<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { art } from "../home/home";
import {
  authNotice,
  loginAccount,
  registerOrReset,
  requestCode,
} from "../core/auth";
import { errorMessage } from "../core/api";
import { useCodeCountdown } from "../core/useCodeCountdown";
import UiIcon from "../ui/UiIcon.vue";
const route = useRoute(),
  router = useRouter();
const stage = ref<"intro" | "transition" | "login">("intro"),
  mode = ref<"login" | "register" | "reset">("login");
const email = ref(""),
  password = ref(""),
  confirmation = ref(""),
  code = ref(""),
  visible = ref(false),
  error = ref(authNotice.value),
  notice = ref(""),
  busy = ref(false),
  sending = ref(false);
const locked = computed(() => busy.value || sending.value);
const codeKey = () => `${mode.value}:${email.value.trim().toLowerCase()}`;
const { remaining, markSent } = useCodeCountdown(codeKey);
const flight = ref<HTMLElement>(),
  solid = ref<HTMLElement>(),
  landing = ref<HTMLImageElement>(),
  scene = ref<HTMLElement>(),
  intro = ref<HTMLElement>(),
  emailInput = ref<HTMLInputElement>();
let animations: Animation[] = [];
let alive = true;
const title = computed(
  () => ({ login: "登录", register: "注册", reset: "找回密码" })[mode.value],
);
function showLogin() {
  stage.value = "login";
  nextTick(() => emailInput.value?.focus());
}
function start() {
  if (stage.value !== "intro") return;
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
    showLogin();
    return;
  }
  const origin = flight.value!.getBoundingClientRect(),
    destination = landing.value!.getBoundingClientRect();
  const dx =
      destination.x + destination.width / 2 - origin.x - origin.width / 2,
    dy =
      destination.y +
      destination.height / 2 -
      origin.y -
      origin.height / 2 -
      12;
  const end = `translate(${dx}px,${dy}px) scale(${destination.width / origin.width})`;
  stage.value = "transition";
  animations = [
    flight.value!.animate(
      [
        { offset: 0, transform: "translate(0,0) scale(1)" },
        { offset: 0.55, transform: "translate(0,-14px) scale(1.1)" },
        { offset: 0.7, transform: "translate(0,0) scale(1)" },
        { offset: 1, transform: end },
      ],
      {
        duration: 1350,
        fill: "forwards",
        easing: "cubic-bezier(.25,.1,.25,1)",
      },
    ),
    solid.value!.animate(
      [
        { offset: 0, transform: "rotateX(-5deg) rotateY(-18deg)" },
        { offset: 0.35, transform: "rotateX(-12deg) rotateY(170deg)" },
        { offset: 0.72, transform: "rotateX(6deg) rotateY(360deg)" },
        { offset: 1, transform: "rotateX(0deg) rotateY(360deg)" },
      ],
      { duration: 1350, fill: "forwards", easing: "ease-in-out" },
    ),
    scene.value!.animate(
      [
        { opacity: 0, transform: "translateY(12px)" },
        { opacity: 1, transform: "translateY(0)" },
      ],
      { duration: 594, delay: 621, fill: "forwards", easing: "ease-out" },
    ),
  ];
  intro.value
    ?.querySelectorAll(".intro-label,.intro-shadow,.intro-orbit")
    .forEach((el) =>
      animations.push(
        el.animate([{ opacity: 1 }, { opacity: 0 }], {
          duration: 400,
          fill: "forwards",
        }),
      ),
    );
  Promise.allSettled(animations.map((a) => a.finished)).then(() => {
    if (alive) showLogin();
  });
}
function changeMode(value: "login" | "register" | "reset") {
  if (locked.value) return;
  mode.value = value;
  error.value = "";
  notice.value = authNotice.value = "";
  password.value = confirmation.value = code.value = "";
  visible.value = false;
}
async function sendCode() {
  if (locked.value || remaining.value || mode.value === "login") return;
  const address = email.value.trim().toLowerCase();
  error.value = notice.value = "";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
    error.value = "请输入有效的邮箱地址";
    return;
  }
  const identity = codeKey();
  sending.value = true;
  try {
    const result = await requestCode(
      address,
      mode.value === "register" ? "register" : "password_reset",
    );
    markSent(identity);
    notice.value = result.message;
  } catch (failure) {
    error.value = errorMessage(failure);
  } finally {
    sending.value = false;
  }
}
async function submit() {
  if (locked.value) return;
  error.value = "";
  notice.value = "";
  const address = email.value.trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
    error.value = "请输入有效的邮箱地址";
    return;
  }
  if (!password.value) {
    error.value = "请输入密码";
    return;
  }
  if (mode.value !== "login") {
    if (password.value.length < 8) {
      error.value = "密码至少 8 位";
      return;
    }
    if (password.value !== confirmation.value) {
      error.value = "两次输入的密码不一致";
      return;
    }
    if (!code.value.trim()) {
      error.value = "请输入邮箱验证码";
      return;
    }
  }
  const submittedMode = mode.value;
  busy.value = true;
  try {
    if (submittedMode !== "login") {
      await registerOrReset(submittedMode, {
        email: address,
        password: password.value,
        confirmation: confirmation.value,
        code: code.value.trim(),
      });
      mode.value = "login";
      password.value = confirmation.value = code.value = "";
      visible.value = false;
      notice.value =
        submittedMode === "register"
          ? "注册成功，请登录"
          : "密码已重置，请登录";
      return;
    }
    await loginAccount(address, password.value);
    password.value = "";
    const redirect = String(route.query.redirect || "/home");
    await router.push(
      redirect.startsWith("/") &&
        !redirect.startsWith("//") &&
        !/[\\\u0000-\u001f]/.test(redirect) &&
        redirect !== "/" &&
        !redirect.startsWith("/login")
        ? redirect
        : "/home",
    );
  } catch (failure) {
    error.value = errorMessage(failure);
  } finally {
    busy.value = false;
  }
}
watch(authNotice, (value) => {
  if (value) error.value = value;
});
watch(
  () => route.query.form,
  (value) => {
    if (["login", "register", "reset"].includes(String(value))) {
      changeMode(value as "login" | "register" | "reset");
      showLogin();
    }
  },
);
onMounted(() => {
  if (
    route.query.form ||
    matchMedia("(prefers-reduced-motion: reduce)").matches
  )
    showLogin();
});
onBeforeUnmount(() => {
  alive = false;
  animations.forEach((a) => a.cancel());
});
</script>
<template>
  <main
    class="auth-page"
    :data-state="stage"
    style="--rest: rotateX(-5deg) rotateY(-18deg)"
  >
    <div class="ambient-background" aria-hidden="true">
      <img :src="art['login-background']" alt="" />
    </div>
    <div ref="scene" class="auth-scene" :inert="stage !== 'login'">
      <header class="topbar">
        <div class="brand">
          <img
            ref="landing"
            class="header-logo"
            :src="art['careerpilot-logo']"
            alt="CareerPilot 标志"
          /><span class="brand-name">CareerPilot</span>
        </div>
      </header>
      <section class="login-panel">
        <form novalidate @submit.prevent="submit">
          <h1>{{ title }}</h1>
          <label class="login-field"
            ><span>邮箱</span
            ><input
              ref="emailInput"
              v-model="email"
              :disabled="locked"
              type="email"
              name="email"
              autocomplete="email" /></label
          ><label class="login-field password-field"
            ><span>{{ mode === "reset" ? "新密码" : "密码" }}</span>
            <div class="password-wrap">
              <input
                v-model="password"
                :disabled="locked"
                :aria-label="mode === 'reset' ? '新密码' : '密码'"
                :type="visible ? 'text' : 'password'"
                name="password"
                :autocomplete="
                  mode === 'login' ? 'current-password' : 'new-password'
                "
              /><button
                id="password-toggle"
                type="button"
                :aria-label="visible ? '隐藏密码' : '显示密码'"
                @click="visible = !visible"
              >
                <UiIcon :name="visible ? 'eye-off' : 'eye'" :size="20" />
              </button></div></label
          ><template v-if="mode !== 'login'"
            ><label class="login-field auth-confirmation"
              ><span>确认密码</span
              ><input
                v-model="confirmation"
                :disabled="locked"
                type="password"
                autocomplete="new-password"
            /></label>
            <div class="auth-code">
              <label class="login-field"
                ><span>邮箱验证码</span
                ><input
                  v-model="code"
                  :disabled="locked"
                  inputmode="numeric"
                  maxlength="6" /></label
              ><button
                type="button"
                class="text-link"
                :disabled="locked || remaining > 0"
                @click="sendCode"
              >
                {{
                  sending
                    ? "发送中…"
                    : remaining
                      ? `${remaining}s 后重发`
                      : "获取验证码"
                }}
              </button>
            </div></template
          >
          <div v-else class="forgot-row">
            <button
              type="button"
              class="text-link"
              :disabled="locked"
              @click="changeMode('reset')"
            >
              忘记密码？
            </button>
          </div>
          <p
            class="form-error"
            :class="{ 'form-notice': !error && notice }"
            :role="error ? 'alert' : 'status'"
          >
            {{ error || notice }}
          </p>
          <button class="login-submit" type="submit" :disabled="locked">
            {{ busy ? `${title}中…` : title }}
          </button>
          <div class="register-row">
            <template v-if="mode === 'login'"
              >还没有账号？<button
                type="button"
                class="text-link"
                :disabled="locked"
                @click="changeMode('register')"
              >
                立即注册
              </button></template
            ><button
              v-else
              type="button"
              class="text-link"
              :disabled="locked"
              @click="changeMode('login')"
            >
              返回登录
            </button>
          </div>
        </form>
      </section>
    </div>
    <div v-show="stage !== 'login'" ref="intro" class="intro">
      <div class="intro-backdrop" />
      <div class="intro-orbit" />
      <div class="intro-orbit second" />
      <div class="intro-shadow" />
      <div ref="flight" class="logo-flight">
        <button
          class="logo-control"
          aria-label="点击 CareerPilot 标志进入登录"
          :disabled="stage !== 'intro'"
          @click="start"
        >
          <span ref="solid" class="logo-solid"
            ><span
              v-for="n in 10"
              :key="n"
              class="logo-layer"
              :style="{
                transform: `translateZ(${-n * 2}px)`,
                background: '#dce7fb',
              }" /><img
              class="logo-face logo-back"
              :src="art['careerpilot-logo']"
              alt="" /><img
              class="logo-face"
              :src="art['careerpilot-logo']"
              alt="CareerPilot"
          /></span>
        </button>
      </div>
      <div class="intro-label">
        <strong>CareerPilot</strong>
      </div>
    </div>
  </main>
</template>
<style scoped src="./login.css"></style>
<style scoped>
.ambient-background img {
  width: 100%;
  height: 100%;
  object-fit: fill;
}
.intro-backdrop {
  background: transparent;
}
.intro-orbit {
  width: 600px;
  height: 280px;
  left: calc(50% - 300px);
  top: calc(50% - 140px);
  border-color: #cfdcf4;
  opacity: 0.65;
}
.intro-orbit.second {
  width: 670px;
  height: 310px;
  left: calc(50% - 335px);
  top: calc(50% - 155px);
  opacity: 0.42;
}
.intro-shadow {
  background: #91a9d366;
  filter: blur(14px);
}
.auth-page[data-state="login"] .auth-scene {
  opacity: 1;
  transform: none;
}
.auth-page[data-state="login"] .header-logo {
  opacity: 1;
}
.auth-page[data-state="login"] .ambient-background {
  opacity: 0.65;
}
.logo-control:disabled {
  opacity: 1;
}
.intro-label {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.intro-label > span {
  font-size: 12px;
  color: #96a5bd;
  letter-spacing: 1px;
}
.form-error {
  height: auto;
  min-height: 18px;
  line-height: 1.7;
}
.form-notice {
  color: #39765d;
}
.auth-confirmation {
  margin-top: 20px;
}
.auth-code {
  display: flex;
  gap: 15px;
  align-items: center;
}
.auth-code > .login-field {
  flex: 1;
  margin-bottom: 8px;
}
.auth-code > .text-link {
  flex: none;
  margin-top: 18px;
}
.login-panel {
  max-height: calc(100svh - 120px);
  overflow-y: auto;
}
.login-panel:has(.auth-confirmation) {
  padding-top: 28px;
  padding-bottom: 28px;
}
.login-panel:has(.auth-confirmation) h1 {
  margin-bottom: 20px;
}
.auth-page {
  min-height: 660px;
}
</style>
