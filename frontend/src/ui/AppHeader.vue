<script setup lang="ts">
import { art } from "../home/home";
import { state } from "../core/state";
import UiIcon from "./UiIcon.vue";
</script>
<template>
  <header class="home-header">
    <RouterLink to="/home" class="home-brand"
      ><img
        class="brand-logo"
        :src="art['careerpilot-logo']"
        alt="CareerPilot 标志"
      /><span>CareerPilot</span></RouterLink
    >
    <div class="home-user">
      <span
        class="user-avatar avatar-default"
        role="img"
        :aria-label="state.account.role === 'admin' ? '管理员头像' : '用户头像'"
        ><img
          v-if="state.account.role === 'admin'"
          :src="art['admin-avatar']"
          alt="" /><img
          v-else-if="state.account.avatarUrl"
          :src="state.account.avatarUrl"
          alt="" />
        <UiIcon v-else name="user" :size="24" /></span
      ><span class="user-greeting">{{
        state.account.role === "admin"
          ? "管理员"
          : `您好，${state.account.name}`
      }}</span>
    </div>
  </header>
</template>
