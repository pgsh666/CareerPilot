import { onBeforeUnmount, onMounted, watch, type Ref } from "vue";
import { navigationDirection, navigationDuration } from "./navigationMotion";

// Only the content travels. The header, background and navigation stay mounted.
// Outgoing content is an inert visual snapshot, so route resources (including
// microphone recognition) are released immediately rather than after animation.
export function usePageMotion(
  viewport: Ref<HTMLElement | undefined>,
  snapshots: Ref<HTMLElement | undefined>,
  options: {
    direction?: Ref<number>;
    distance?: () => number;
    snapshotClass?: string;
    snapshotLeft?: string;
    disabled?: Ref<boolean>;
  } = {},
) {
  const direction = options.direction || navigationDirection;
  const distance = options.distance || (() => innerWidth);
  const entering = new Map<Element, Animation>();
  const leaving = new Set<Animation>();
  const preference = matchMedia("(prefers-reduced-motion: reduce)");
  const reduceMotion = () => preference.matches || !!options.disabled?.value;
  let hasSnapshot = false;

  function leave(element: Element, done: () => void) {
    if (!reduceMotion() && snapshots.value && viewport.value) {
      const source = element as HTMLElement;
      const copy = source.cloneNode(true) as HTMLElement;
      const rect = source.getBoundingClientRect();
      copy.removeAttribute("id");
      copy
        .querySelectorAll("[id]")
        .forEach((node) => node.removeAttribute("id"));
      copy.setAttribute("inert", "");
      copy.setAttribute("aria-hidden", "true");
      copy.classList.add(options.snapshotClass || "route-snapshot");
      Object.assign(copy.style, {
        position: "absolute",
        top: "0",
        left: options.snapshotLeft || "5.5555555%",
        margin: "0",
        width: `${rect.width}px`,
        height: `${rect.height}px`,
        transform: getComputedStyle(source).transform,
      });
      snapshots.value.append(copy);
      const originals = [source, ...source.querySelectorAll<HTMLElement>("*")];
      const copies = [copy, ...copy.querySelectorAll<HTMLElement>("*")];
      originals.forEach((node, i) => {
        const duplicate = copies[i];
        if (!duplicate) return;
        duplicate.scrollTop = node.scrollTop;
        duplicate.scrollLeft = node.scrollLeft;
        if (node !== source && node.getAnimations().length)
          duplicate.style.transform = getComputedStyle(node).transform;
        if (
          node instanceof HTMLTextAreaElement ||
          node instanceof HTMLInputElement
        )
          (duplicate as HTMLInputElement).value = node.value;
        if (node instanceof HTMLSelectElement)
          (duplicate as HTMLSelectElement).value = node.value;
        if (node instanceof HTMLInputElement)
          (duplicate as HTMLInputElement).checked = node.checked;
      });
      const animation = copy.animate(
        [
          { transform: copy.style.transform },
          {
            transform: `translateX(${-direction.value * distance()}px)`,
          },
        ],
        {
          duration: navigationDuration,
          easing: "cubic-bezier(.32,.08,.18,1)",
          fill: "forwards",
        },
      );
      leaving.add(animation);
      hasSnapshot = true;
      animation.finished
        .catch(() => {})
        .finally(() => {
          copy.remove();
          leaving.delete(animation);
        });
    }
    done();
  }

  function beforeEnter(element: Element) {
    if (!hasSnapshot || reduceMotion()) return;
    hasSnapshot = false;
    const content = element as HTMLElement;
    content.style.transform = `translateX(${direction.value * distance()}px)`;
    content.style.willChange = "transform";
  }

  function enter(element: Element, done: () => void) {
    const content = element as HTMLElement;
    if (!content.style.transform || reduceMotion()) {
      content.style.removeProperty("transform");
      done();
      return;
    }
    const animation = content.animate(
      [{ transform: content.style.transform }, { transform: "translateX(0)" }],
      { duration: navigationDuration, easing: "cubic-bezier(.32,.08,.18,1)" },
    );
    content.style.removeProperty("transform");
    entering.set(element, animation);
    animation.finished
      .catch(() => {})
      .finally(() => {
        if (entering.get(element) === animation) {
          content.style.removeProperty("will-change");
          entering.delete(element);
          done();
        }
      });
  }

  function enterCancelled(element: Element) {
    const content = element as HTMLElement;
    const transform = getComputedStyle(content).transform;
    entering.get(element)?.cancel();
    entering.delete(element);
    content.style.transform = transform;
    content.style.removeProperty("will-change");
  }

  function settle() {
    entering.forEach((animation) => animation.finish());
    leaving.forEach((animation) => animation.finish());
  }
  if (options.disabled)
    watch(
      options.disabled,
      (disabled) => {
        if (!disabled) return;
        settle();
        snapshots.value?.replaceChildren();
        hasSnapshot = false;
      },
      { flush: "sync" },
    );
  onMounted(() => {
    window.addEventListener("resize", settle);
    preference.addEventListener("change", settle);
  });
  onBeforeUnmount(() => {
    window.removeEventListener("resize", settle);
    preference.removeEventListener("change", settle);
    entering.forEach((animation) => animation.cancel());
    leaving.forEach((animation) => animation.cancel());
    snapshots.value?.replaceChildren();
  });
  return { leave, beforeEnter, enter, enterCancelled };
}
