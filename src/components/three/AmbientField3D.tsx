/**
 * AmbientField3D — app-wide ambient particle field.
 *
 * A sparse cloud of softly glowing motes in brand greens/teals drifting very
 * slowly behind the in-app pages (dashboard, portfolio, …). Deliberately
 * quieter than the landing constellation: no links, low opacity, gentle
 * pointer parallax only.
 *
 * Lazy-loaded (default export) and mounted only when motion is allowed —
 * see the reduced-motion gate in App.tsx.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { makeGlowSprite, mountScene } from "@/lib/three/mountScene";

const COUNT = 130;
const FIELD = { x: 26, y: 15, z: 8 };
const COLORS = [0x1fb57a, 0x2dd4bf, 0x34d399, 0x94a3b8];

export default function AmbientField3D() {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    let mx = 0;
    let my = 0;
    const onMouse = (e: MouseEvent) => {
      mx = e.clientX / window.innerWidth - 0.5;
      my = e.clientY / window.innerHeight - 0.5;
    };
    window.addEventListener("pointermove", onMouse, { passive: true });

    const unmount = mountScene(
      el,
      ({ scene }) => {
        const group = new THREE.Group();
        scene.add(group);

        const positions = new Float32Array(COUNT * 3);
        const colors = new Float32Array(COUNT * 3);
        const seeds = new Float32Array(COUNT);
        const colorObj = new THREE.Color();
        for (let i = 0; i < COUNT; i++) {
          positions[i * 3] = (Math.random() - 0.5) * FIELD.x;
          positions[i * 3 + 1] = (Math.random() - 0.5) * FIELD.y;
          positions[i * 3 + 2] = (Math.random() - 0.5) * FIELD.z;
          colorObj.setHex(COLORS[Math.floor(Math.random() * COLORS.length)]);
          colors[i * 3] = colorObj.r;
          colors[i * 3 + 1] = colorObj.g;
          colors[i * 3 + 2] = colorObj.b;
          seeds[i] = Math.random() * Math.PI * 2;
        }

        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
        const tex = makeGlowSprite();
        const mat = new THREE.PointsMaterial({
          size: 0.34,
          map: tex,
          vertexColors: true,
          transparent: true,
          opacity: 0.4,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
          sizeAttenuation: true,
        });
        group.add(new THREE.Points(geo, mat));

        const posAttr = geo.getAttribute("position") as THREE.BufferAttribute;
        const arr = posAttr.array as Float32Array;
        let cmx = 0;
        let cmy = 0;

        return {
          onFrame(elapsed) {
            // Slow orbital drift per particle — sine offsets, no velocity state.
            for (let i = 0; i < COUNT; i++) {
              const s = seeds[i];
              arr[i * 3 + 1] += Math.sin(elapsed * 0.12 + s) * 0.0012;
              arr[i * 3] += Math.cos(elapsed * 0.08 + s * 1.7) * 0.0012;
            }
            posAttr.needsUpdate = true;

            cmx += (mx - cmx) * 0.03;
            cmy += (my - cmy) * 0.03;
            group.rotation.y = elapsed * 0.012 + cmx * 0.22;
            group.rotation.x = cmy * 0.12;
          },
          dispose() {
            geo.dispose();
            mat.dispose();
            tex.dispose();
          },
        };
      },
      { cameraZ: 12, maxDpr: 1.5 },
    );

    return () => {
      window.removeEventListener("pointermove", onMouse);
      unmount();
    };
  }, []);

  return <div ref={mountRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />;
}
