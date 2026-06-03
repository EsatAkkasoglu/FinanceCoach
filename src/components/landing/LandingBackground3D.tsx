/**
 * LandingBackground3D — ambient Three.js constellation behind the landing page.
 *
 * A field of glowing accent-green nodes drifting in 3D, with faint links drawn
 * between nearby nodes (a nod to FinCoach's multi-agent graph). The whole group
 * reacts to two inputs:
 *   • scroll  — camera dollies in and the field rotates as you move down the page
 *   • pointer — smoothed parallax tilt toward the cursor
 *
 * Performance / etiquette:
 *   • Lazy-loaded (default export) so WebGL never blocks first paint.
 *   • DPR capped, link graph rebuilt every other frame, draw-range trimmed.
 *   • rAF paused while the tab is hidden; full WebGL teardown on unmount.
 *   • Only mounted when motion is allowed — see LandingPage's reduced-motion gate.
 *
 * Imperative raw-three style intentionally mirrors GoalsHero.tsx.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";

const NODE_COUNT = 80;
const LINK_DIST = 2.4; // connect nodes closer than this (world units)
const MAX_PAIRS = NODE_COUNT * 6; // hard cap on drawn links
const FIELD = { x: 18, y: 11, z: 6 }; // bounds the nodes wrap within

export default function LandingBackground3D() {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    let W = el.clientWidth;
    let H = el.clientHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, W / H, 0.1, 100);
    camera.position.z = 14;

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.setSize(W, H);
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);

    // Group holds nodes + links so scroll/pointer rotate them as one.
    const group = new THREE.Group();
    scene.add(group);

    // Node positions + gentle per-axis velocities.
    const positions = new Float32Array(NODE_COUNT * 3);
    const velocities = new Float32Array(NODE_COUNT * 3);
    for (let i = 0; i < NODE_COUNT; i++) {
      positions[i * 3] = (Math.random() - 0.5) * FIELD.x;
      positions[i * 3 + 1] = (Math.random() - 0.5) * FIELD.y;
      positions[i * 3 + 2] = (Math.random() - 0.5) * FIELD.z;
      velocities[i * 3] = (Math.random() - 0.5) * 0.004;
      velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.004;
      velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.004;
    }

    // Soft white radial sprite — tinted to accent green via material color.
    const sprite = document.createElement("canvas");
    sprite.width = sprite.height = 64;
    const sctx = sprite.getContext("2d")!;
    const grad = sctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.3, "rgba(255,255,255,0.55)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    sctx.fillStyle = grad;
    sctx.fillRect(0, 0, 64, 64);
    const tex = new THREE.CanvasTexture(sprite);

    const nodeGeo = new THREE.BufferGeometry();
    nodeGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const nodeMat = new THREE.PointsMaterial({
      size: 0.5,
      map: tex,
      color: 0x1fb57a,
      transparent: true,
      opacity: 0.9,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });
    const points = new THREE.Points(nodeGeo, nodeMat);
    group.add(points);

    // Link segments, rebuilt each frame within the distance threshold.
    const linkPositions = new Float32Array(MAX_PAIRS * 2 * 3);
    const linkGeo = new THREE.BufferGeometry();
    linkGeo.setAttribute("position", new THREE.BufferAttribute(linkPositions, 3));
    const linkMat = new THREE.LineBasicMaterial({
      color: 0x1fb57a,
      transparent: true,
      opacity: 0.14,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const lines = new THREE.LineSegments(linkGeo, linkMat);
    group.add(lines);

    // ── Interaction state ──
    let scrollN = 0; // viewport-normalized scroll offset
    let mx = 0;
    let my = 0; // raw pointer (−0.5…0.5)
    let cmx = 0;
    let cmy = 0; // smoothed pointer

    const onScroll = () => {
      scrollN = window.scrollY / Math.max(1, window.innerHeight);
    };
    const onMouse = (e: MouseEvent) => {
      mx = e.clientX / window.innerWidth - 0.5;
      my = e.clientY / window.innerHeight - 0.5;
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pointermove", onMouse, { passive: true });

    const posAttr = nodeGeo.getAttribute("position") as THREE.BufferAttribute;
    const linkAttr = linkGeo.getAttribute("position") as THREE.BufferAttribute;
    const arr = posAttr.array as Float32Array;
    const la = linkAttr.array as Float32Array;
    const link2 = LINK_DIST * LINK_DIST;
    const hx = FIELD.x / 2;
    const hy = FIELD.y / 2;
    const hz = FIELD.z / 2;

    let frame = 0;
    let raf = 0;

    function animate() {
      raf = requestAnimationFrame(animate);
      frame++;

      // Drift + wrap nodes.
      for (let i = 0; i < NODE_COUNT; i++) {
        const x = (arr[i * 3] += velocities[i * 3]);
        const y = (arr[i * 3 + 1] += velocities[i * 3 + 1]);
        const z = (arr[i * 3 + 2] += velocities[i * 3 + 2]);
        if (x > hx) arr[i * 3] = -hx;
        else if (x < -hx) arr[i * 3] = hx;
        if (y > hy) arr[i * 3 + 1] = -hy;
        else if (y < -hy) arr[i * 3 + 1] = hy;
        if (z > hz) arr[i * 3 + 2] = -hz;
        else if (z < -hz) arr[i * 3 + 2] = hz;
      }
      posAttr.needsUpdate = true;

      // Rebuild proximity links every other frame.
      if (frame % 2 === 0) {
        let p = 0;
        for (let i = 0; i < NODE_COUNT && p < MAX_PAIRS; i++) {
          for (let j = i + 1; j < NODE_COUNT && p < MAX_PAIRS; j++) {
            const dx = arr[i * 3] - arr[j * 3];
            const dy = arr[i * 3 + 1] - arr[j * 3 + 1];
            const dz = arr[i * 3 + 2] - arr[j * 3 + 2];
            if (dx * dx + dy * dy + dz * dz < link2) {
              la[p * 6] = arr[i * 3];
              la[p * 6 + 1] = arr[i * 3 + 1];
              la[p * 6 + 2] = arr[i * 3 + 2];
              la[p * 6 + 3] = arr[j * 3];
              la[p * 6 + 4] = arr[j * 3 + 1];
              la[p * 6 + 5] = arr[j * 3 + 2];
              p++;
            }
          }
        }
        linkGeo.setDrawRange(0, p * 2);
        linkAttr.needsUpdate = true;
      }

      // Smooth the pointer parallax.
      cmx += (mx - cmx) * 0.05;
      cmy += (my - cmy) * 0.05;

      // Scroll dollies the camera in and spins the field; pointer tilts it.
      const s = Math.min(scrollN, 2);
      group.rotation.y = frame * 0.0006 + cmx * 0.5 + s * 0.6;
      group.rotation.x = cmy * 0.35 + s * 0.15;
      camera.position.z = 14 - s * 1.6;

      renderer.render(scene, camera);
    }
    animate();

    // Pause the loop while the tab is hidden.
    const onVis = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) animate();
    };
    document.addEventListener("visibilitychange", onVis);

    const onResize = () => {
      if (!mountRef.current) return;
      W = mountRef.current.clientWidth;
      H = mountRef.current.clientHeight;
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
      renderer.setSize(W, H);
    };
    window.addEventListener("resize", onResize);

    const elRef = el;
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onMouse);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVis);
      renderer.dispose();
      nodeGeo.dispose();
      nodeMat.dispose();
      linkGeo.dispose();
      linkMat.dispose();
      tex.dispose();
      if (elRef.contains(renderer.domElement)) elRef.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={mountRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />;
}
