/**
 * GoalsHero — Three.js ambient particle canvas.
 *
 * Renders ~80 glowing coin-like orbs that drift upward and loop.
 * Sits behind the header text as a purely decorative layer.
 * Cleans up WebGL context on unmount to avoid memory leaks.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";

const PARTICLE_COUNT = 80;
const COLORS = [0x22c55e, 0x10b981, 0xf59e0b, 0x34d399, 0xfbbf24];

export function GoalsHero() {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    const W = el.clientWidth;
    const H = el.clientHeight;

    // Scene
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, W / H, 0.1, 100);
    camera.position.z = 5;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(W, H);
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);

    // Particles
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const colors = new Float32Array(PARTICLE_COUNT * 3);
    const speeds = new Float32Array(PARTICLE_COUNT);
    const sizes = new Float32Array(PARTICLE_COUNT);

    const colorObj = new THREE.Color();

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      positions[i * 3]     = (Math.random() - 0.5) * 12;   // x
      positions[i * 3 + 1] = (Math.random() - 0.5) * 4;    // y (start spread)
      positions[i * 3 + 2] = (Math.random() - 0.5) * 2;    // z depth

      colorObj.setHex(COLORS[Math.floor(Math.random() * COLORS.length)]);
      colors[i * 3]     = colorObj.r;
      colors[i * 3 + 1] = colorObj.g;
      colors[i * 3 + 2] = colorObj.b;

      speeds[i] = 0.003 + Math.random() * 0.006;
      sizes[i]  = 4 + Math.random() * 10;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color",    new THREE.BufferAttribute(colors,    3));
    geometry.setAttribute("size",     new THREE.BufferAttribute(sizes,     1));

    // Circle texture for coins
    const canvas2d = document.createElement("canvas");
    canvas2d.width = 32; canvas2d.height = 32;
    const ctx = canvas2d.getContext("2d")!;
    const grad = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
    grad.addColorStop(0,   "rgba(255,255,255,0.9)");
    grad.addColorStop(0.5, "rgba(255,255,255,0.4)");
    grad.addColorStop(1,   "rgba(255,255,255,0)");
    ctx.fillStyle = grad;
    ctx.beginPath(); ctx.arc(16, 16, 16, 0, Math.PI * 2);
    ctx.fill();
    const texture = new THREE.CanvasTexture(canvas2d);

    const material = new THREE.PointsMaterial({
      size: 0.15,
      map: texture,
      vertexColors: true,
      transparent: true,
      opacity: 0.65,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });

    const points = new THREE.Points(geometry, material);
    scene.add(points);

    // Animation
    let frameId: number;
    const posAttr = geometry.getAttribute("position") as THREE.BufferAttribute;

    function animate() {
      frameId = requestAnimationFrame(animate);

      for (let i = 0; i < PARTICLE_COUNT; i++) {
        posAttr.array[i * 3 + 1] += speeds[i];
        // Slight horizontal drift
        posAttr.array[i * 3]     += Math.sin(Date.now() * 0.001 + i) * 0.001;
        // Loop: when particle drifts above top, reset to bottom
        if ((posAttr.array[i * 3 + 1] as number) > 2.5) {
          posAttr.array[i * 3 + 1] = -2.5;
          posAttr.array[i * 3]     = (Math.random() - 0.5) * 12;
        }
      }
      posAttr.needsUpdate = true;

      // Gentle scene rotation
      points.rotation.z += 0.0002;

      renderer.render(scene, camera);
    }
    animate();

    // Resize
    function onResize() {
      if (!mountRef.current) return;
      const w = mountRef.current.clientWidth;
      const h = mountRef.current.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    window.addEventListener("resize", onResize);

    const elRef = el;
    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      geometry.dispose();
      material.dispose();
      texture.dispose();
      if (elRef && elRef.contains(renderer.domElement)) elRef.removeChild(renderer.domElement);
    };
  }, []);

  return (
    <div
      ref={mountRef}
      className="pointer-events-none absolute inset-0 overflow-hidden rounded-2xl"
      aria-hidden="true"
    />
  );
}
