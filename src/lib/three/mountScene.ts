/**
 * mountScene — shared lifecycle harness for the imperative Three.js scenes.
 *
 * Owns the boilerplate every ambient canvas needs:
 *   • WebGLRenderer with alpha, capped DPR, high-performance hint
 *   • rAF loop driven by THREE.Clock (elapsed + delta passed to onFrame)
 *   • pause while the tab is hidden (visibility API)
 *   • ResizeObserver-based resize (panels resize with sidebar collapse,
 *     not just the window)
 *   • full teardown: loop, observers, renderer, caller disposables
 *
 * Callers build their scene graph in `build` and return the frame callback
 * plus a dispose for their own geometries/materials/textures.
 */
import * as THREE from "three";

export interface BuildContext {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  width: number;
  height: number;
}

export interface BuildResult {
  /** Called once per frame before render. */
  onFrame?: (elapsed: number, delta: number) => void;
  /** Dispose caller-owned GPU resources (geometries, materials, textures). */
  dispose?: () => void;
}

export interface MountOptions {
  /** Camera field of view in degrees. Default 60. */
  fov?: number;
  /** Initial camera z position. Default 10. */
  cameraZ?: number;
  /** Device pixel ratio cap. Default 1.75. */
  maxDpr?: number;
}

export function mountScene(
  el: HTMLElement,
  build: (ctx: BuildContext) => BuildResult,
  opts: MountOptions = {},
): () => void {
  const { fov = 60, cameraZ = 10, maxDpr = 1.75 } = opts;

  // WebGL2 may be unavailable (older GPUs, WebKitGTK on Linux, a blocklisted or
  // disabled GPU). three r184 is WebGL2-only, so probe on a throwaway canvas and
  // bail to a no-op teardown rather than throwing — callers keep working and the
  // static CSS backdrop shows through; only the decorative motion layer is skipped.
  if (!document.createElement("canvas").getContext("webgl2")) {
    return () => {};
  }

  let width = Math.max(1, el.clientWidth);
  let height = Math.max(1, el.clientHeight);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(fov, width / height, 0.1, 100);
  camera.position.z = cameraZ;

  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, maxDpr));
    renderer.setSize(width, height);
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);
  } catch (err) {
    // Context creation can still fail after a positive probe (driver crash,
    // too many live contexts). Degrade silently to the static backdrop.
    console.warn("mountScene: WebGL renderer unavailable, skipping scene", err);
    return () => {};
  }

  const { onFrame, dispose } = build({ scene, camera, renderer, width, height });

  // Plain timer instead of THREE.Clock (deprecated in r184). Delta is clamped
  // so returning from a hidden tab can't produce a giant animation jump.
  let last = performance.now();
  let elapsed = 0;
  let raf = 0;
  let running = true;

  function animate() {
    raf = requestAnimationFrame(animate);
    const now = performance.now();
    const delta = Math.min((now - last) / 1000, 0.1);
    last = now;
    elapsed += delta;
    onFrame?.(elapsed, delta);
    renderer.render(scene, camera);
  }
  animate();

  const onVis = () => {
    if (document.hidden) {
      cancelAnimationFrame(raf);
      running = false;
    } else if (!running) {
      running = true;
      last = performance.now();
      animate();
    }
  };
  document.addEventListener("visibilitychange", onVis);

  // WebGL context can be lost (GPU reset, driver hiccup, tab eviction). Pause the
  // loop on loss and resume on restore instead of silently freezing the canvas.
  const onContextLost = (e: Event) => {
    e.preventDefault();
    cancelAnimationFrame(raf);
    running = false;
  };
  const onContextRestored = () => {
    if (!running) {
      running = true;
      last = performance.now();
      animate();
    }
  };
  renderer.domElement.addEventListener("webglcontextlost", onContextLost);
  renderer.domElement.addEventListener("webglcontextrestored", onContextRestored);

  const ro = new ResizeObserver(() => {
    width = Math.max(1, el.clientWidth);
    height = Math.max(1, el.clientHeight);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  });
  ro.observe(el);

  return () => {
    cancelAnimationFrame(raf);
    document.removeEventListener("visibilitychange", onVis);
    renderer.domElement.removeEventListener("webglcontextlost", onContextLost);
    renderer.domElement.removeEventListener("webglcontextrestored", onContextRestored);
    ro.disconnect();
    dispose?.();
    renderer.dispose();
    if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
  };
}

/** Soft radial sprite texture shared by the particle scenes. */
export function makeGlowSprite(size = 64): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new THREE.CanvasTexture(canvas);
  const half = size / 2;
  const grad = ctx.createRadialGradient(half, half, 0, half, half, half);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,255,255,0.5)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}
