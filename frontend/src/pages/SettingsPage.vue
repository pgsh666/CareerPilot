<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRouter } from "vue-router";
import AppShell from "../ui/AppShell.vue";
import UiModal from "../ui/UiModal.vue";
import UiIcon from "../ui/UiIcon.vue";
import { notify, state } from "../core/state";
import {
  accountBusy,
  changeEmail,
  changePassword,
  closeAccount,
  requestCode,
  saveProfile,
  signOut,
  uploadAvatar,
} from "../core/auth";
import { errorMessage } from "../core/api";
import { useCodeCountdown } from "../core/useCodeCountdown";
import { isPreviewMode } from "../core/runtime";
const router = useRouter();
const name = ref(state.account.name),
  avatar = ref(state.account.avatar),
  modal = ref(""),
  error = ref("");
const oldPassword = ref(""),
  newPassword = ref(""),
  confirmPassword = ref(""),
  newEmail = ref(""),
  code = ref(""),
  deletion = ref("");
const savingName = ref(false),
  sending = ref(false),
  working = ref(false),
  notice = ref("");
const locked = computed(
  () =>
    accountBusy.value ||
    working.value ||
    sending.value ||
    savingName.value ||
    pickingAvatar.value,
);
const avatarFile = ref<File | null>(null),
  avatarPreview = ref(""),
  avatarInput = ref<HTMLInputElement>();
const pickingAvatar = ref(false);
let avatarSelection = 0;
const customPreview = computed(
  () =>
    avatarPreview.value ||
    (avatar.value === state.account.avatar ? state.account.avatarUrl : ""),
);
function clearAvatarFile() {
  avatarSelection++;
  if (avatarPreview.value) URL.revokeObjectURL(avatarPreview.value);
  avatarPreview.value = "";
  avatarFile.value = null;
  pickingAvatar.value = false;
  if (avatarInput.value) avatarInput.value.value = "";
}
function useDefaultAvatar() {
  clearAvatarFile();
  avatar.value = "default";
}
async function chooseAvatar(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  clearAvatarFile();
  error.value = "";
  if (file.size > 2 * 1024 * 1024) {
    error.value = "头像图片不能超过2MB";
    return;
  }
  if (!/\.(jpe?g|png|webp)$/i.test(file.name)) {
    error.value = "请选择JPG、PNG或WebP图片";
    return;
  }
  const version = avatarSelection,
    owner = state.account.id;
  const url = URL.createObjectURL(file);
  pickingAvatar.value = true;
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    if (
      version !== avatarSelection ||
      owner !== state.account.id ||
      modal.value !== "avatar"
    ) {
      URL.revokeObjectURL(url);
      return;
    }
    if (
      image.naturalWidth * image.naturalHeight > 16_000_000 ||
      Math.max(image.naturalWidth, image.naturalHeight) > 10000
    )
      throw new Error("图片尺寸过大，请缩小后重试");
    avatarFile.value = file;
    avatarPreview.value = url;
    avatar.value = "pending-upload";
  } catch (failure) {
    URL.revokeObjectURL(url);
    if (version === avatarSelection && modal.value === "avatar")
      error.value =
        failure instanceof Error && failure.name !== "EncodingError"
          ? failure.message
          : "图片无法读取，请重新选择";
  } finally {
    if (version === avatarSelection) pickingAvatar.value = false;
  }
}
watch(modal, (value) => {
  if (value !== "avatar") clearAvatarFile();
});
watch(
  () => state.account.id,
  () => {
    modal.value = "";
    clearAvatarFile();
  },
);
onBeforeUnmount(clearAvatarFile);
const codeKey = () => `email_change:${newEmail.value.trim().toLowerCase()}`;
const { remaining, markSent } = useCodeCountdown(codeKey);
watch(
  () => state.account.name,
  (value) => (name.value = value),
);
function open(kind: string) {
  if (locked.value) return;
  clearAvatarFile();
  modal.value = kind;
  error.value = "";
  notice.value = "";
  avatar.value = state.account.avatar;
  oldPassword.value =
    newPassword.value =
    confirmPassword.value =
    newEmail.value =
    code.value =
    deletion.value =
      "";
}
async function saveName() {
  if (locked.value) return;
  if (!name.value.trim()) {
    notify("请输入用户名");
    return;
  }
  if (name.value.trim().length > 24) {
    notify("用户名最多 24 个字符");
    return;
  }
  savingName.value = true;
  try {
    await saveProfile({ name: name.value.trim() });
    notify("修改已保存");
  } catch (failure) {
    notify(errorMessage(failure));
  } finally {
    savingName.value = false;
  }
}
async function sendEmailCode() {
  if (locked.value || remaining.value) return;
  const email = newEmail.value.trim().toLowerCase();
  error.value = notice.value = "";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    error.value = "请输入有效的新邮箱";
    return;
  }
  const identity = codeKey();
  sending.value = true;
  try {
    const result = await requestCode(email, "email_change");
    markSent(identity);
    notice.value = result.message;
  } catch (failure) {
    error.value = errorMessage(failure);
  } finally {
    sending.value = false;
  }
}
async function confirm() {
  if (locked.value) return;
  error.value = "";
  if (modal.value === "avatar") {
    working.value = true;
    try {
      if (avatarFile.value) await uploadAvatar(avatarFile.value);
      else if (avatar.value !== state.account.avatar)
        await saveProfile({ avatar: avatar.value });
      modal.value = "";
      notify("头像已更换");
    } catch (failure) {
      error.value = errorMessage(failure);
    } finally {
      working.value = false;
    }
    return;
  }
  if (modal.value === "logout") {
    working.value = true;
    try {
      await signOut();
      await router.push("/login?form=login");
    } catch (failure) {
      error.value = errorMessage(failure);
    } finally {
      working.value = false;
    }
    return;
  }
  if (modal.value === "password") {
    if (!oldPassword.value) {
      error.value = "请输入当前密码";
      return;
    }
    if (!newPassword.value) {
      error.value = "请输入新密码";
      return;
    }
    if (newPassword.value.length < 8) {
      error.value = "新密码至少 8 位";
      return;
    }
    if (newPassword.value === oldPassword.value) {
      error.value = "新密码不能与当前密码相同";
      return;
    }
    if (newPassword.value !== confirmPassword.value) {
      error.value = "两次输入的新密码不一致";
      return;
    }
    working.value = true;
    try {
      await changePassword({
        current_password: oldPassword.value,
        password: newPassword.value,
        confirmation: confirmPassword.value,
      });
      oldPassword.value = newPassword.value = confirmPassword.value = "";
      notify("密码已修改，请重新登录");
      await router.push("/login?form=login");
    } catch (failure) {
      error.value = errorMessage(failure);
    } finally {
      working.value = false;
    }
    return;
  }
  if (modal.value === "email") {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(newEmail.value)) {
      error.value = "请输入有效的新邮箱";
      return;
    }
    if (!code.value.trim()) {
      error.value = "请输入邮箱验证码";
      return;
    }
    working.value = true;
    try {
      await changeEmail({
        email: newEmail.value.trim().toLowerCase(),
        code: code.value.trim(),
      });
      code.value = "";
      notify("邮箱已更新，请重新登录");
      await router.push("/login?form=login");
    } catch (failure) {
      error.value = errorMessage(failure);
    } finally {
      working.value = false;
    }
    return;
  }
  if (modal.value === "delete") {
    if (deletion.value !== state.account.email) {
      error.value = "请输入当前账号邮箱以确认";
      return;
    }
    working.value = true;
    try {
      await closeAccount(deletion.value);
      deletion.value = "";
      notify("账号已永久关闭，个人数据保留30天后清理");
      await router.push("/login?form=login");
    } catch (failure) {
      error.value = errorMessage(failure);
    } finally {
      working.value = false;
    }
  }
}
</script>
<template>
  <AppShell title="账号管理" class="settings-shell"
    ><section class="ui-panel settings-panel">
      <div class="settings-heading">
        <h2>个人资料</h2>
        <button class="ui-button primary" :disabled="locked" @click="saveName">
          {{ savingName ? "保存中…" : "保存修改" }}
        </button>
      </div>
      <div class="profile-content">
        <div class="profile-picture">
          <div class="large-avatar avatar-default">
            <img
              v-if="state.account.avatarUrl"
              :src="state.account.avatarUrl"
              alt="当前头像"
            />
            <UiIcon v-else name="user" :size="48" />
          </div>
          <button class="ui-button soft" @click="open('avatar')">
            更换头像
          </button>
        </div>
        <div class="profile-fields">
          <label class="ui-field"
            ><span>用户名</span
            ><input
              v-model="name"
              :disabled="locked"
              maxlength="24"
              @keyup.enter="saveName"
          /></label>
          <div class="settings-email">
            <span class="email-label">绑定邮箱</span>
            <div>
              <span>{{ state.account.email }}</span
              ><span class="ui-badge green">已验证</span
              ><button class="ui-button" @click="open('email')">
                更换绑定邮箱
              </button>
            </div>
          </div>
        </div>
      </div>
      <div class="account-security">
        <h2>账号安全</h2>
        <button class="ui-button" @click="open('password')">修改密码</button
        ><button class="ui-button" @click="open('logout')">退出登录</button
        ><button class="text-button danger" @click="open('delete')">
          注销账号
        </button>
      </div>
    </section>
    <UiModal
      :open="!!modal"
      :busy="locked"
      :title="
        {
          avatar: '更换头像',
          password: '修改密码',
          email: '更换绑定邮箱',
          logout: '退出登录',
          delete: '注销账号',
        }[modal] || ''
      "
      @close="modal = ''"
      ><template v-if="modal === 'avatar'">
        <div class="avatar-upload">
          <div class="avatar-upload-preview">
            <img v-if="customPreview" :src="customPreview" alt="头像上传预览" />
            <span v-else class="large-avatar"
              ><UiIcon name="user" :size="38"
            /></span>
            <span>{{
              avatarFile
                ? "确认后保存此图片"
                : customPreview
                  ? "当前上传头像"
                  : "通用头像"
            }}</span>
          </div>
          <div>
            <input
              v-if="!isPreviewMode"
              ref="avatarInput"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              aria-label="选择头像图片"
              hidden
              @change="chooseAvatar"
            />
            <button
              v-if="!isPreviewMode"
              class="ui-button soft"
              :disabled="locked"
              @click="avatarInput?.click()"
            >
              {{ pickingAvatar ? "读取中…" : "上传自己的图片" }}
            </button>
            <button
              class="text-button"
              :disabled="locked"
              @click="useDefaultAvatar"
            >
              使用默认头像
            </button>
            <button
              v-if="
                state.account.avatarUrl &&
                !avatarFile &&
                avatar !== state.account.avatar
              "
              class="text-button"
              :disabled="locked"
              @click="avatar = state.account.avatar"
            >
              使用当前上传头像
            </button>
            <p>JPG、PNG、WebP · 最大2MB · 按预览居中显示</p>
            <p v-if="isPreviewMode">请在本机服务页面上传头像图片。</p>
          </div>
        </div></template
      >
      <template v-else-if="modal === 'password'"
        ><label class="ui-field"
          ><span>当前密码</span
          ><input
            v-model="oldPassword"
            :disabled="locked"
            type="password"
            autocomplete="current-password" /></label
        ><label class="ui-field"
          ><span>新密码</span
          ><input
            v-model="newPassword"
            :disabled="locked"
            type="password"
            autocomplete="new-password" /></label
        ><label class="ui-field"
          ><span>确认新密码</span
          ><input
            v-model="confirmPassword"
            :disabled="locked"
            type="password"
            autocomplete="new-password"
            @keyup.enter="confirm" /></label></template
      ><template v-else-if="modal === 'email'"
        ><label class="ui-field"
          ><span>新邮箱</span
          ><input
            v-model="newEmail"
            :disabled="locked"
            type="email"
            autocomplete="email"
        /></label>
        <div class="email-code">
          <label class="ui-field"
            ><span>邮箱验证码</span
            ><input
              v-model="code"
              :disabled="locked"
              inputmode="numeric"
              maxlength="6" /></label
          ><button
            class="ui-button"
            :disabled="locked || remaining > 0"
            @click="sendEmailCode"
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
      <p v-else-if="modal === 'logout'" class="confirm-copy">
        确认退出当前账号？
      </p>
      <template v-else-if="modal === 'delete'"
        ><p class="confirm-copy">
          {{
            isPreviewMode
              ? "注销后账号及关联资料将无法恢复。"
              : "账号将永久关闭，无法重新启用。个人数据保留30天后清理，匿名费用记录保留；同邮箱可注册全新普通账号，不恢复旧数据。"
          }}
        </p>
        <label class="ui-field"
          ><span>确认账号邮箱</span
          ><input
            v-model="deletion"
            type="email"
            :placeholder="state.account.email" /></label
      ></template>
      <p class="inline-error" role="alert">{{ error }}</p>
      <p v-if="!error && notice" class="inline-notice" role="status">
        {{ notice }}
      </p>
      <template #footer
        ><button class="ui-button" :disabled="locked" @click="modal = ''">
          取消</button
        ><button
          class="ui-button"
          :class="modal === 'delete' ? 'danger' : 'primary'"
          :disabled="locked"
          @click="confirm"
        >
          {{ working ? "处理中…" : "确认" }}
        </button></template
      ></UiModal
    ></AppShell
  >
</template>
<style scoped>
.settings-shell :deep(.page-heading) {
  padding-left: 3.125%;
  padding-right: 3.125%;
}
.settings-panel {
  width: 93.75%;
  margin: 0 auto;
  padding: 28px 40px 0;
}
.settings-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}
.settings-heading h2,
.account-security h2 {
  font-size: var(--ui-title);
}
.settings-heading .ui-button {
  min-width: 136px;
}
.profile-content {
  display: grid;
  grid-template-columns: 22% 1fr;
  margin-top: 36px;
  min-height: calc(var(--workspace-height) * 0.46);
}
.profile-picture {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  gap: 34px;
  border-right: 1px solid #dce3ee;
  padding-top: 12px;
}
.large-avatar {
  overflow: hidden;
  width: clamp(90px, 7.777778vw, 148px);
  aspect-ratio: 1;
  background: #eef3ff;
  border: 1px solid #dce5f6;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #8299c4;
  font-size: 40px;
  font-weight: 600;
}
.large-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.avatar-upload {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 12px 0;
}
.avatar-upload p {
  color: #667895;
  font-size: 13px;
  margin: 10px 0 0;
}
.avatar-upload .text-button {
  margin-left: 12px;
}
.avatar-upload-preview {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #667895;
}
.avatar-upload-preview img {
  width: 76px;
  height: 76px;
  border-radius: 50%;
  object-fit: cover;
}
.avatar-upload-preview .large-avatar {
  width: 76px;
}
.large-avatar > .ui-icon {
  width: 50%;
  height: 50%;
}
.profile-picture .ui-button {
  min-width: 112px;
  font-size: 0.9em;
}
.profile-fields {
  padding-left: 40px;
  max-width: 760px;
}
.profile-fields .ui-field {
  margin-bottom: 52px;
}
.profile-fields .ui-field input {
  height: 44px;
}
.settings-email {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.email-label {
  color: #667895;
  font-size: 0.95em;
}
.settings-email > div {
  display: flex;
  align-items: center;
  gap: 30px;
}
.settings-email .ui-button {
  margin-left: auto;
  font-size: 0.9em;
  padding: 0 16px;
}
.account-security {
  display: grid;
  grid-template-columns: 22% 1fr 1fr 1fr;
  gap: 18px;
  align-items: center;
  border-top: 1px solid #dce3ee;
  margin-top: auto;
  min-height: calc(var(--workspace-height) * 0.27);
}
.account-security > .ui-button {
  justify-self: start;
  min-width: 168px;
}
.account-security > .text-button {
  justify-self: end;
  font-size: 0.9em;
}
.email-code {
  display: flex;
  gap: 18px;
  align-items: center;
}
.email-code .ui-field {
  flex: 1;
}
.email-code .ui-button {
  margin-top: 9px;
}
@media (max-width: 1200px) {
  .settings-panel {
    padding: 24px 28px 0;
  }
  .profile-fields {
    padding-left: 28px;
  }
  .settings-email > div {
    gap: 16px;
  }
  .account-security {
    gap: 12px;
  }
  .account-security > .ui-button {
    min-width: 130px;
  }
  .settings-email .ui-button {
    padding: 0 10px;
  }
  .profile-fields .ui-field {
    margin-bottom: 38px;
  }
}
</style>
