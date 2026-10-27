<script setup lang="ts">
defineProps<{ title: string }>();
</script>
<template>
  <main class="business-content business-page route-screen">
    <div class="page-heading">
      <h1>{{ title }}</h1>
      <div class="page-actions"><slot name="actions" /></div>
    </div>
    <div class="business-workspace"><slot /></div>
    <div class="business-navigation-row" aria-hidden="true">
      <div class="navigation-space" />
    </div>
  </main>
</template>
