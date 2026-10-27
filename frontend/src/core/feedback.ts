const interactive = [
  "button:not(.logo-control)",
  ".ui-button",
  ".hero-start",
  ".card-action",
  ".text-button",
  ".home-navigation a",
  ".card-more",
].join(",");

// Delegation keeps feedback consistent for routed pages and teleported dialogs.
// It never delays a click, prevents native behavior, or changes disabled states.
export function installFeedback() {
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const pointers = new Map<number, HTMLElement>();
  const animations = new WeakMap<HTMLElement, Animation>();
  let keyboard: HTMLElement | undefined;
  function target(node: EventTarget | null) {
    const element =
      node instanceof Element ? node.closest<HTMLElement>(interactive) : null;
    return element &&
      !element.matches(':disabled,[aria-disabled="true"]') &&
      !element.closest("[inert]")
      ? element
      : undefined;
  }
  function press(element: HTMLElement, event?: PointerEvent) {
    animations.get(element)?.cancel();
    element.dataset.pressed = "true";
    if (event) {
      const rect = element.getBoundingClientRect();
      element.style.setProperty("--press-x", `${event.clientX - rect.x}px`);
      element.style.setProperty("--press-y", `${event.clientY - rect.y}px`);
    }
    if (!motion.matches)
      animations.set(
        element,
        element.animate([{ scale: "1" }, { scale: ".965" }], {
          duration: 90,
          fill: "forwards",
          easing: "ease-out",
        }),
      );
  }
  function release(element: HTMLElement, bounce = true) {
    const scale = getComputedStyle(element).scale;
    animations.get(element)?.cancel();
    delete element.dataset.pressed;
    if (!element.isConnected || motion.matches || !bounce) return;
    animations.set(
      element,
      element.animate(
        [
          { scale: scale === "none" ? ".965" : scale, offset: 0 },
          { scale: "1.025", offset: 0.44 },
          { scale: ".995", offset: 0.72 },
          { scale: "1", offset: 1 },
        ],
        { duration: 420, easing: "cubic-bezier(.22,.8,.3,1)" },
      ),
    );
  }
  function down(event: PointerEvent) {
    if (event.button !== 0) return;
    const element = target(event.target);
    if (!element) return;
    pointers.set(event.pointerId, element);
    press(element, event);
  }
  function up(event: PointerEvent) {
    const element = pointers.get(event.pointerId);
    if (!element) return;
    release(element, event.type !== "pointercancel");
    pointers.delete(event.pointerId);
  }
  function keydown(event: KeyboardEvent) {
    if (event.repeat || !["Enter", " "].includes(event.key)) return;
    const element = target(event.target);
    if (!element) return;
    keyboard = element;
    press(element);
  }
  function keyup(event: KeyboardEvent) {
    if (keyboard && ["Enter", " "].includes(event.key)) {
      release(keyboard);
      keyboard = undefined;
    }
  }
  function cancel() {
    pointers.forEach((element) => release(element, false));
    pointers.clear();
    if (keyboard) release(keyboard, false);
    keyboard = undefined;
  }
  document.addEventListener("pointerdown", down, { passive: true });
  document.addEventListener("pointerup", up, { passive: true });
  document.addEventListener("pointercancel", up, { passive: true });
  document.addEventListener("keydown", keydown);
  document.addEventListener("keyup", keyup);
  window.addEventListener("blur", cancel);
  return () => {
    cancel();
    document.removeEventListener("pointerdown", down);
    document.removeEventListener("pointerup", up);
    document.removeEventListener("pointercancel", up);
    document.removeEventListener("keydown", keydown);
    document.removeEventListener("keyup", keyup);
    window.removeEventListener("blur", cancel);
  };
}
