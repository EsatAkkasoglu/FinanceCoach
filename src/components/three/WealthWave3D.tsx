/**
 * WealthWave3D — animated point-grid terrain for the dashboard hero.
 *
 * A low-angle field of glowing points displaced by layered traveling sine
 * waves — reads as a living "market surface" behind the net-worth numeral.
 * Brightness follows wave height so crests glow brighter than troughs.
 *
 * Decorative only: pointer-events-none container, masked at the edges by the
 * parent, mounted behind the hero content. Gate on reduced motion upstream.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { makeGlowSprite, mountScene } from "@/lib/three/mountScene";

const COLS = 110;
const ROWS = 34;
const SPACING = 0.42;
const BASE = new THREE.Color(0x1fb57a);
const CREST = new THREE.Color(0x6ee7b7);

function waveHeight(x: number, z: number, t: number): number {
  return (
    Math.sin(x * 0.55 + t * 0.9) * 0.32 +
    Math.sin(z * 0.8 - t * 0.6) * 0.22 +
    Math.sin((x + z) * 0.32 + t * 0.45) * 0.26
  );
}

export default function WealthWave3D() {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    const unmount = mountScene(
      el,
      ({ scene, camera }) => {
        camera.position.set(0, 3.4, 9.5);
        camera.lookAt(0, 0, -2);

        const count = COLS * ROWS;
        const positions = new Float32Array(count * 3);
        const colors = new Float32Array(count * 3);
        for (let r = 0; r < ROWS; r++) {
          for (let c = 0; c < COLS; c++) {
            const i = r * COLS + c;
            positions[i * 3] = (c - COLS / 2) * SPACING;
            positions[i * 3 + 1] = 0;
            positions[i * 3 + 2] = -r * SPACING * 1.15 + 2;
          }
        }

        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
        const tex = makeGlowSprite();
        const mat = new THREE.PointsMaterial({
          size: 0.16,
          map: tex,
          vertexColors: true,
          transparent: true,
          opacity: 0.85,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
          sizeAttenuation: true,
        });
        scene.add(new THREE.Points(geo, mat));

        const posAttr = geo.getAttribute("position") as THREE.BufferAttribute;
        const colAttr = geo.getAttribute("color") as THREE.BufferAttribute;
        const pos = posAttr.array as Float32Array;
        const col = colAttr.array as Float32Array;
        const mixed = new THREE.Color();

        return {
          onFrame(elapsed) {
            for (let i = 0; i < count; i++) {
              const x = pos[i * 3];
              const z = pos[i * 3 + 2];
              const h = waveHeight(x, z, elapsed);
              pos[i * 3 + 1] = h;
              // Crests brighten toward mint; depth dims toward the horizon.
              const lift = THREE.MathUtils.clamp((h + 0.8) / 1.6, 0, 1);
              const depthFade = THREE.MathUtils.clamp(1 - (-z + 2) / (ROWS * SPACING * 1.3), 0.12, 1);
              mixed.lerpColors(BASE, CREST, lift).multiplyScalar(depthFade * (0.35 + lift * 0.65));
              col[i * 3] = mixed.r;
              col[i * 3 + 1] = mixed.g;
              col[i * 3 + 2] = mixed.b;
            }
            posAttr.needsUpdate = true;
            colAttr.needsUpdate = true;
          },
          dispose() {
            geo.dispose();
            mat.dispose();
            tex.dispose();
          },
        };
      },
      { fov: 55, cameraZ: 9.5, maxDpr: 1.5 },
    );

    return unmount;
  }, []);

  return <div ref={mountRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />;
}
