/**
 * HeroOrb3D — holographic wireframe globe behind the landing hero cards.
 *
 * Three nested layers rotating at different rates:
 *   • outer wireframe icosahedron (brand green, faint)
 *   • inner solid sphere with additive glow (the "core")
 *   • a tilted ring of orbiting particles (data in motion)
 *
 * The whole group tilts toward the pointer, matching HeroVisual's parallax
 * so the CSS card stack and the WebGL orb read as one 3D composition.
 * Lazy-loaded; mount only when motion is allowed.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { makeGlowSprite, mountScene } from "@/lib/three/mountScene";

const RING_COUNT = 110;
const RING_RADIUS = 3.1;

export default function HeroOrb3D() {
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

        // Outer wireframe shell
        const shellGeo = new THREE.IcosahedronGeometry(2.5, 1);
        const shellMat = new THREE.MeshBasicMaterial({
          color: 0x1fb57a,
          wireframe: true,
          transparent: true,
          opacity: 0.16,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const shell = new THREE.Mesh(shellGeo, shellMat);
        group.add(shell);

        // Second, finer shell rotating the other way for moiré depth
        const innerShellGeo = new THREE.IcosahedronGeometry(1.9, 2);
        const innerShellMat = new THREE.MeshBasicMaterial({
          color: 0x2dd4bf,
          wireframe: true,
          transparent: true,
          opacity: 0.07,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const innerShell = new THREE.Mesh(innerShellGeo, innerShellMat);
        group.add(innerShell);

        // Glowing core
        const coreGeo = new THREE.SphereGeometry(0.85, 24, 24);
        const coreMat = new THREE.MeshBasicMaterial({
          color: 0x1fb57a,
          transparent: true,
          opacity: 0.32,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        });
        const core = new THREE.Mesh(coreGeo, coreMat);
        group.add(core);

        // Orbiting particle ring (tilted like a planetary system)
        const ring = new THREE.Group();
        ring.rotation.x = Math.PI / 2.6;
        group.add(ring);

        const ringPositions = new Float32Array(RING_COUNT * 3);
        const angles = new Float32Array(RING_COUNT);
        const radii = new Float32Array(RING_COUNT);
        for (let i = 0; i < RING_COUNT; i++) {
          angles[i] = Math.random() * Math.PI * 2;
          radii[i] = RING_RADIUS + (Math.random() - 0.5) * 0.7;
        }
        const ringGeo = new THREE.BufferGeometry();
        ringGeo.setAttribute("position", new THREE.BufferAttribute(ringPositions, 3));
        const tex = makeGlowSprite();
        const ringMat = new THREE.PointsMaterial({
          size: 0.14,
          map: tex,
          color: 0x6ee7b7,
          transparent: true,
          opacity: 0.8,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
          sizeAttenuation: true,
        });
        ring.add(new THREE.Points(ringGeo, ringMat));
        const ringAttr = ringGeo.getAttribute("position") as THREE.BufferAttribute;
        const ringArr = ringAttr.array as Float32Array;

        let cmx = 0;
        let cmy = 0;

        return {
          onFrame(elapsed, delta) {
            shell.rotation.y += delta * 0.12;
            shell.rotation.x += delta * 0.03;
            innerShell.rotation.y -= delta * 0.2;
            core.scale.setScalar(1 + Math.sin(elapsed * 1.4) * 0.06);

            for (let i = 0; i < RING_COUNT; i++) {
              const a = angles[i] + elapsed * 0.25;
              ringArr[i * 3] = Math.cos(a) * radii[i];
              ringArr[i * 3 + 1] = Math.sin(a * 2.3 + angles[i]) * 0.12;
              ringArr[i * 3 + 2] = Math.sin(a) * radii[i];
            }
            ringAttr.needsUpdate = true;

            cmx += (mx - cmx) * 0.05;
            cmy += (my - cmy) * 0.05;
            group.rotation.y = cmx * 0.6;
            group.rotation.x = cmy * 0.4;
          },
          dispose() {
            shellGeo.dispose();
            shellMat.dispose();
            innerShellGeo.dispose();
            innerShellMat.dispose();
            coreGeo.dispose();
            coreMat.dispose();
            ringGeo.dispose();
            ringMat.dispose();
            tex.dispose();
          },
        };
      },
      { fov: 50, cameraZ: 9, maxDpr: 1.75 },
    );

    return () => {
      window.removeEventListener("pointermove", onMouse);
      unmount();
    };
  }, []);

  return <div ref={mountRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />;
}
