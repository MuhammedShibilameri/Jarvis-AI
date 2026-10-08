/* ============================================================
   Ultron-style holographic orb, ported to plain JavaScript.

   Source: https://github.com/SAGAR-TAMANG/ultron-by-sagar-builds
   (lib/orbScene.ts) - MIT license. TypeScript stripped, uses the
   THREE global provided by the classic build in this folder.
   ============================================================ */

(function () {
  "use strict";

  var HOME_POSITION = new THREE.Vector3(0, 0.5, 5.5);
  var MIN_DISTANCE = 0.6;
  var MAX_DISTANCE = 40;
  var AUTO_SPIN = 0.0009;

  function createOrbScene(container) {
    var width = container.clientWidth || 1;
    var height = container.clientHeight || 1;

    // ---------- SCENE ----------
    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(55, width / height, 0.1, 500);
    camera.position.copy(HOME_POSITION);

    var renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: "low-power" });
    renderer.setSize(width, height);
    renderer.setPixelRatio(1);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.8;
    container.appendChild(renderer.domElement);

    // Note: the EffectComposer / UnrealBloomPass chain renders black in the
    // WebView2 in this project, so the scene is drawn directly instead.

    // Lightweight controls: the full OrbitControls script failed to
    // initialize in some WebView2 sessions, so the camera is orbited with a
    // tiny spherical drift each frame instead. Hand gestures still steer it.
    var controls = {
      target: new THREE.Vector3(0, 0, 0),
      update: function () {},
    };

    // ---------- COLORS ----------
    var C_BRIGHT = 0xffaa30;
    var C_MID = 0xdd7700;
    var C_DIM = 0x884400;
    var C_FAINT = 0x553300;
    var C_HOT = 0xffcc66;

    // ---------- ORB ROOT ----------
    var orbGroup = new THREE.Group();
    scene.add(orbGroup);

    // ---------- MATERIAL HELPERS ----------
    function lineMat(color, opacity) {
      opacity = opacity === undefined ? 1 : opacity;
      return new THREE.LineBasicMaterial({
        color: color,
        transparent: true,
        opacity: opacity,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      });
    }

    // ---------- UTILITY: Ring at a latitude ----------
    function latRing(radius, lat, segs) {
      segs = segs === undefined ? 120 : segs;
      var r = radius * Math.cos(lat);
      var y = radius * Math.sin(lat);
      var pts = [];
      for (var i = 0; i <= segs; i++) {
        var a = (i / segs) * Math.PI * 2;
        pts.push(new THREE.Vector3(r * Math.cos(a), y, r * Math.sin(a)));
      }
      return new THREE.BufferGeometry().setFromPoints(pts);
    }

    // ---------- UTILITY: Meridian ----------
    function meridian(radius, lon, segs) {
      segs = segs === undefined ? 120 : segs;
      var pts = [];
      for (var i = 0; i <= segs; i++) {
        var lat = (i / segs) * Math.PI - Math.PI / 2;
        pts.push(
          new THREE.Vector3(
            radius * Math.cos(lat) * Math.cos(lon),
            radius * Math.sin(lat),
            radius * Math.cos(lat) * Math.sin(lon),
          ),
        );
      }
      return new THREE.BufferGeometry().setFromPoints(pts);
    }

    // ============================================================
    // LAYER 1: OUTER SHELL — dense wireframe grid
    // ============================================================
    var outerShell = new THREE.Group();
    var R1 = 2.0;

    // Dense latitude rings
    for (var li = -15; li <= 15; li++) {
      var lat = (li / 15) * (Math.PI / 2) * 0.95;
      var opacity = li % 3 === 0 ? 0.5 : 0.12;
      var color = li % 3 === 0 ? C_MID : C_FAINT;
      outerShell.add(new THREE.Line(latRing(R1, lat), lineMat(color, opacity)));
    }

    // Dense meridians
    for (var mi = 0; mi < 24; mi++) {
      var lon = (mi / 24) * Math.PI * 2;
      var isMajor = mi % 6 === 0;
      outerShell.add(
        new THREE.Line(
          meridian(R1, lon),
          lineMat(isMajor ? C_MID : C_FAINT, isMajor ? 0.6 : 0.1),
        ),
      );
    }

    // 4 bright cross meridians (the "plus" shape) — wide bands
    var CROSS_LINES = 18;
    var CROSS_SPREAD = 0.25;
    for (var ci = 0; ci < 4; ci++) {
      var clon = (ci / 4) * Math.PI * 2;
      for (var cj = 0; cj < CROSS_LINES; cj++) {
        var t = (cj / (CROSS_LINES - 1)) * 2 - 1;
        var coffset = (t * CROSS_SPREAD) / 2;
        var falloff = 1 - Math.abs(t) * 0.7;
        var copacity = 0.85 * falloff;
        var ccolor = Math.abs(t) < 0.3 ? C_BRIGHT : C_MID;
        outerShell.add(
          new THREE.Line(meridian(R1, clon + coffset, 200), lineMat(ccolor, copacity)),
        );
      }
    }

    // Bright equator band — wide
    var EQ_LINES = 20;
    var EQ_SPREAD = 0.35;
    for (var ej = 0; ej < EQ_LINES; ej++) {
      var et = (ej / (EQ_LINES - 1)) * 2 - 1;
      var eoffset = (et * EQ_SPREAD) / 2;
      var efalloff = 1 - Math.abs(et) * 0.65;
      var eopacity = 0.8 * efalloff;
      var ecolor = Math.abs(et) < 0.3 ? C_BRIGHT : C_MID;
      outerShell.add(
        new THREE.Line(latRing(R1, eoffset, 200), lineMat(ecolor, eopacity)),
      );
    }

    orbGroup.add(outerShell);

    // ============================================================
    // LAYER 2: GRID PANELS on the sphere surface
    // ============================================================
    var panelGroup = new THREE.Group();

    function createSpherePanel(latCenter, lonCenter, latSpan, lonSpan, radius, divisions) {
      divisions = divisions === undefined ? 4 : divisions;
      var group = new THREE.Group();
      var mat = lineMat(C_DIM, 0.25);

      // horizontal lines
      for (var hi = 0; hi <= divisions; hi++) {
        var hlat = latCenter - latSpan / 2 + (hi / divisions) * latSpan;
        var hpts = [];
        for (var hj = 0; hj <= divisions * 4; hj++) {
          var hlon = lonCenter - lonSpan / 2 + (hj / (divisions * 4)) * lonSpan;
          hpts.push(
            new THREE.Vector3(
              radius * Math.cos(hlat) * Math.cos(hlon),
              radius * Math.sin(hlat),
              radius * Math.cos(hlat) * Math.sin(hlon),
            ),
          );
        }
        group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(hpts), mat));
      }

      // vertical lines
      for (var vj = 0; vj <= divisions; vj++) {
        var vlon = lonCenter - lonSpan / 2 + (vj / divisions) * lonSpan;
        var vpts = [];
        for (var vi = 0; vi <= divisions * 4; vi++) {
          var vlat = latCenter - latSpan / 2 + (vi / (divisions * 4)) * latSpan;
          vpts.push(
            new THREE.Vector3(
              radius * Math.cos(vlat) * Math.cos(vlon),
              radius * Math.sin(vlat),
              radius * Math.cos(vlat) * Math.sin(vlon),
            ),
          );
        }
        group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(vpts), mat));
      }

      return group;
    }

    // Scatter panels across the sphere
    for (var pi = 0; pi < 30; pi++) {
      var plat = (Math.random() - 0.5) * Math.PI * 0.8;
      var plon = Math.random() * Math.PI * 2;
      var psize = 0.15 + Math.random() * 0.25;
      var panel = createSpherePanel(
        plat,
        plon,
        psize,
        psize,
        R1 + 0.01,
        3 + Math.floor(Math.random() * 3),
      );
      panelGroup.add(panel);
    }
    orbGroup.add(panelGroup);

    // ============================================================
    // LAYER 3: SECONDARY SHELL — offset, partial arcs
    // ============================================================
    var shell2 = new THREE.Group();
    var R2 = 2.12;

    // Partial arcs at random latitudes
    for (var ai = 0; ai < 16; ai++) {
      var alat = (Math.random() - 0.5) * Math.PI * 0.85;
      var astart = Math.random() * Math.PI * 2;
      var aarc = 0.3 + Math.random() * 1.2;
      var apts = [];
      var aSegs = 60;
      var ar = R2 * Math.cos(alat);
      var ay = R2 * Math.sin(alat);
      for (var aj = 0; aj <= aSegs; aj++) {
        var aa = astart + (aj / aSegs) * aarc;
        apts.push(new THREE.Vector3(ar * Math.cos(aa), ay, ar * Math.sin(aa)));
      }
      shell2.add(
        new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(apts),
          lineMat(C_MID, 0.2 + Math.random() * 0.3),
        ),
      );
    }

    // Partial meridian arcs
    for (var mai = 0; mai < 12; mai++) {
      var mlon = Math.random() * Math.PI * 2;
      var mstart = (Math.random() - 0.5) * Math.PI * 0.8;
      var marc = 0.3 + Math.random() * 0.8;
      var mpts = [];
      var mSegs = 40;
      for (var mj = 0; mj <= mSegs; mj++) {
        var mlat = mstart + (mj / mSegs) * marc;
        mpts.push(
          new THREE.Vector3(
            R2 * Math.cos(mlat) * Math.cos(mlon),
            R2 * Math.sin(mlat),
            R2 * Math.cos(mlat) * Math.sin(mlon),
          ),
        );
      }
      shell2.add(
        new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(mpts),
          lineMat(C_DIM, 0.15 + Math.random() * 0.2),
        ),
      );
    }
    orbGroup.add(shell2);

    // ============================================================
    // LAYER 4: INNER CORE — spiral geodesic
    // ============================================================
    var innerCore = new THREE.Group();
    var R3 = 0.9;

    // Dense spirals
    for (var si = 0; si < 8; si++) {
      var spts = [];
      var turns = 3 + Math.random() * 2;
      var ssegs = 300;
      var sphase = (si / 8) * Math.PI * 2;
      for (var sj = 0; sj <= ssegs; sj++) {
        var st = sj / ssegs;
        var slat = st * Math.PI - Math.PI / 2;
        var slon = st * turns * Math.PI * 2 + sphase;
        spts.push(
          new THREE.Vector3(
            R3 * Math.cos(slat) * Math.cos(slon),
            R3 * Math.sin(slat),
            R3 * Math.cos(slat) * Math.sin(slon),
          ),
        );
      }
      innerCore.add(
        new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(spts),
          lineMat(C_BRIGHT, 0.3 + Math.random() * 0.2),
        ),
      );
    }

    // Inner latitude rings
    for (var rli = -6; rli <= 6; rli++) {
      var rlat = (rli / 6) * (Math.PI / 2) * 0.9;
      innerCore.add(new THREE.Line(latRing(R3, rlat, 80), lineMat(C_DIM, 0.2)));
    }

    // Inner meridians
    for (var rmi = 0; rmi < 12; rmi++) {
      var rlon = (rmi / 12) * Math.PI * 2;
      innerCore.add(new THREE.Line(meridian(R3, rlon, 80), lineMat(C_DIM, 0.15)));
    }

    orbGroup.add(innerCore);

    // ============================================================
    // LAYER 5: INNERMOST CORE — bright hot center
    // ============================================================
    var coreR = 0.25;

    // Icosahedron wireframe core
    var icoGeo = new THREE.IcosahedronGeometry(coreR, 1);
    var icoEdges = new THREE.EdgesGeometry(icoGeo);
    var icoWireMat = lineMat(C_HOT, 0.9);
    var icoWire = new THREE.LineSegments(icoEdges, icoWireMat);
    orbGroup.add(icoWire);

    // Glowing center sphere — subtle, see-through
    var coreSphereMat = new THREE.MeshBasicMaterial({
      color: C_HOT,
      transparent: true,
      opacity: 0.15,
      blending: THREE.AdditiveBlending,
    });
    var coreSphere = new THREE.Mesh(new THREE.SphereGeometry(0.15, 16, 16), coreSphereMat);
    orbGroup.add(coreSphere);

    // Larger faint glow
    var glowSphereMat = new THREE.MeshBasicMaterial({
      color: C_MID,
      transparent: true,
      opacity: 0.04,
      blending: THREE.AdditiveBlending,
    });
    var glowSphere = new THREE.Mesh(new THREE.SphereGeometry(0.5, 16, 16), glowSphereMat);
    orbGroup.add(glowSphere);

    // ============================================================
    // CODE TEXT — tiny, dense, scattered
    // ============================================================
    var codeSnippets = [
      "sys.init()", "0xFF3A", "malloc()", ">> SCAN", "void*", "ACK",
      "SYNC OK", "ptr_ref", "exec()", "hash256", "::bind", "core.0",
      "01101001", "10110100", ">>> RDY", "HEAP 4K", "TCP/SYN",
      "mutex.lk", "IRQ 0x7", "DMA xfer", "REG EAX", "FAULT 0",
      "kernel.d", "pipe |>", "chmod +x", "fork()", "SIGTERM",
      "eth0: UP", "AES-256", "RSA 4096", "TLS 1.3", "HTTP/2",
      "latency", "200 OK", "PATCH /", "fn main", "use std",
      "impl Orb", "async {}", "spawn()", "arc::new", ".unwrap",
    ];

    function makeTextSprite(text, size) {
      size = size === undefined ? 0.08 : size;
      var c = document.createElement("canvas");
      c.width = 256;
      c.height = 32;
      var ctx = c.getContext("2d");
      ctx.font = "bold 14px Courier New";
      var alpha = 0.35 + Math.random() * 0.55;
      ctx.fillStyle = "rgba(255, " + ((130 + Math.random() * 80) | 0) + ", " + ((20 + Math.random() * 30) | 0) + ", " + alpha + ")";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(text, 128, 16);
      var tex = new THREE.CanvasTexture(c);
      tex.minFilter = THREE.LinearFilter;
      var s = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: tex,
          transparent: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        }),
      );
      s.scale.set(size * 5, size * 0.7, 1);
      return s;
    }

    function scatterText(count, sizeFn, rFn, speedScale) {
      var group = new THREE.Group();
      for (var i = 0; i < count; i++) {
        var sp = makeTextSprite(
          codeSnippets[Math.floor(Math.random() * codeSnippets.length)],
          sizeFn(),
        );
        var phi = Math.acos(2 * Math.random() - 1);
        var theta = Math.random() * Math.PI * 2;
        var r = rFn();
        sp.position.set(
          r * Math.sin(phi) * Math.cos(theta),
          r * Math.cos(phi),
          r * Math.sin(phi) * Math.sin(theta),
        );
        sp.userData = {
          phi: phi,
          theta: theta,
          r: r,
          speed: (speedScale[0] + Math.random() * speedScale[1]) * (Math.random() > 0.5 ? 1 : -1),
        };
        group.add(sp);
      }
      return group;
    }

    // On outer sphere — dense text coverage
    var textOuter = scatterText(
      1200,
      function () { return 0.04 + Math.random() * 0.04; },
      function () { return R1 + 0.03 + Math.random() * 0.08; },
      [0.0002, 0.0008],
    );
    orbGroup.add(textOuter);

    // On inner core
    var textInner = scatterText(
      100,
      function () { return 0.03 + Math.random() * 0.03; },
      function () { return R3 + 0.02; },
      [0.0005, 0.001],
    );
    orbGroup.add(textInner);

    // Floating ambient text between shells
    var textAmbient = scatterText(
      400,
      function () { return 0.03; },
      function () { return R3 + 0.2 + Math.random() * (R1 - R3 - 0.3); },
      [0.0003, 0.0006],
    );
    orbGroup.add(textAmbient);

    // ============================================================
    // ORBITING DEBRIS / ROCKS
    // ============================================================
    var debrisGeos = [
      new THREE.IcosahedronGeometry(0.012, 0),
      new THREE.IcosahedronGeometry(0.02, 0),
      new THREE.IcosahedronGeometry(0.03, 1),
      new THREE.IcosahedronGeometry(0.008, 0),
      new THREE.TetrahedronGeometry(0.015, 0),
      new THREE.OctahedronGeometry(0.018, 0),
    ];
    var debris = [];
    for (var di = 0; di < 250; di++) {
      var dgeo = debrisGeos[Math.floor(Math.random() * debrisGeos.length)];
      var dmat = new THREE.MeshBasicMaterial({
        color: Math.random() > 0.7 ? C_BRIGHT : C_MID,
        transparent: true,
        opacity: 0.3 + Math.random() * 0.6,
        blending: THREE.AdditiveBlending,
      });
      var mesh = new THREE.Mesh(dgeo, dmat);
      var orbitR = 1.2 + Math.random() * 4.0;
      var dspeed = (0.08 + Math.random() * 0.6) * (Math.random() > 0.5 ? 1 : -1);
      var tiltX = (Math.random() - 0.5) * Math.PI * 0.9;
      var tiltZ = (Math.random() - 0.5) * Math.PI * 0.5;
      var dphase = Math.random() * Math.PI * 2;
      mesh.userData = { orbitR: orbitR, speed: dspeed, tiltX: tiltX, tiltZ: tiltZ, phase: dphase };
      debris.push(mesh);
      orbGroup.add(mesh);

      // ~15% get a faint trailing line
      if (Math.random() > 0.85) {
        var tpts = [];
        for (var tj = 0; tj <= 15; tj++) {
          var ta = -(tj / 15) * 0.3;
          tpts.push(
            new THREE.Vector3(
              orbitR * Math.cos(ta + dphase),
              orbitR * 0.08 * Math.sin(ta * 3),
              orbitR * Math.sin(ta + dphase),
            ),
          );
        }
        var trail = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(tpts),
          lineMat(C_FAINT, 0.08),
        );
        mesh.add(trail);
      }
    }

    // ============================================================
    // DUST PARTICLES — lots of them
    // ============================================================
    var dustCount = 2000;
    var dustPos = new Float32Array(dustCount * 3);

    for (var dui = 0; dui < dustCount; dui++) {
      var rr = 0.5 + Math.pow(Math.random(), 0.6) * 7;
      var dtheta = Math.random() * Math.PI * 2;
      var dphi = Math.acos(2 * Math.random() - 1);
      dustPos[dui * 3] = rr * Math.sin(dphi) * Math.cos(dtheta);
      dustPos[dui * 3 + 1] = rr * Math.cos(dphi);
      dustPos[dui * 3 + 2] = rr * Math.sin(dphi) * Math.sin(dtheta);
    }

    var dustGeo = new THREE.BufferGeometry();
    dustGeo.setAttribute("position", new THREE.Float32BufferAttribute(dustPos, 3));

    var dotC = document.createElement("canvas");
    dotC.width = dotC.height = 64;
    var dCtx = dotC.getContext("2d");
    var grad = dCtx.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, "rgba(255,170,48,1)");
    grad.addColorStop(0.2, "rgba(255,120,20,0.6)");
    grad.addColorStop(0.5, "rgba(200,80,0,0.15)");
    grad.addColorStop(1, "rgba(100,40,0,0)");
    dCtx.fillStyle = grad;
    dCtx.fillRect(0, 0, 64, 64);

    var dustMat = new THREE.PointsMaterial({
      map: new THREE.CanvasTexture(dotC),
      size: 0.04,
      transparent: true,
      opacity: 0.5,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
      color: C_BRIGHT,
    });
    var dustPoints = new THREE.Points(dustGeo, dustMat);
    orbGroup.add(dustPoints);

    // ============================================================
    // SCANNING RINGS
    // ============================================================
    function makeScanRing(radius, thickness) {
      thickness = thickness === undefined ? 0.015 : thickness;
      var geo = new THREE.RingGeometry(radius - thickness, radius + thickness, 120);
      var mat = new THREE.MeshBasicMaterial({
        color: C_BRIGHT,
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      var mesh = new THREE.Mesh(geo, mat);
      mesh.rotation.x = Math.PI / 2;
      return mesh;
    }

    var scanRing1 = makeScanRing(R1, 0.01);
    var scanRing2 = makeScanRing(R1 * 0.7, 0.008);
    orbGroup.add(scanRing1, scanRing2);

    // ============================================================
    // HEXAGONAL NODES — small tech details
    // ============================================================
    for (var hxi = 0; hxi < 15; hxi++) {
      var hphi = Math.acos(2 * Math.random() - 1);
      var htheta = Math.random() * Math.PI * 2;
      var hr = R1 + 0.02;
      var hexGeo = new THREE.CircleGeometry(0.03 + Math.random() * 0.02, 6);
      var hexEdges = new THREE.EdgesGeometry(hexGeo);
      var hex = new THREE.LineSegments(hexEdges, lineMat(C_MID, 0.5));
      hex.position.set(
        hr * Math.sin(hphi) * Math.cos(htheta),
        hr * Math.cos(hphi),
        hr * Math.sin(hphi) * Math.sin(htheta),
      );
      hex.lookAt(0, 0, 0);
      outerShell.add(hex);
    }

    // ============================================================
    // AVATAR HUD — a floating text readout under the orb so Jarvis
    // can show what it is doing / what it heard. The orb itself (the
    // status ring experiment) was removed on request.
    // ============================================================
    var statusLabel = getLabel("");
    statusLabel.position.set(0, -2.15, 0);
    statusLabel.scale.set(2.4, 0.6, 1);
    statusLabel.visible = false;
    scene.add(statusLabel);

    function getLabel(text) {
      var cv = document.createElement("canvas");
      cv.width = 640;
      cv.height = 160;
      var g = cv.getContext("2d");
      g.clearRect(0, 0, cv.width, cv.height);
      g.font = "bold 58px Segoe UI, Arial, sans-serif";
      g.textAlign = "center";
      g.textBaseline = "middle";
      g.shadowColor = "rgba(255,170,48,0.9)";
      g.shadowBlur = 24;
      g.lineWidth = 8;
      g.strokeStyle = "rgba(10,20,35,0.9)";
      g.strokeText(text, cv.width / 2, cv.height / 2);
      g.fillStyle = "#ffcf7a";
      g.fillText(text, cv.width / 2, cv.height / 2);
      var tex = new THREE.CanvasTexture(cv);
      tex.needsUpdate = true;
      var sp = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }),
      );
      sp.userData.canvas = cv;
      sp.userData.tex = tex;
      return sp;
    }

    // ============================================================
    // CAMERA CONTROL
    // ============================================================
    var sphericalScratch = new THREE.Spherical();
    var offsetScratch = new THREE.Vector3();

    function rotateBy(deltaTheta, deltaPhi) {
      offsetScratch.copy(camera.position).sub(controls.target);
      sphericalScratch.setFromVector3(offsetScratch);
      sphericalScratch.theta -= deltaTheta;
      sphericalScratch.phi = THREE.MathUtils.clamp(
        sphericalScratch.phi - deltaPhi,
        0.05,
        Math.PI - 0.05,
      );
      sphericalScratch.makeSafe();
      offsetScratch.setFromSpherical(sphericalScratch);
      camera.position.copy(controls.target).add(offsetScratch);
      camera.lookAt(controls.target);
    }

    function zoomBy(factor) {
      offsetScratch.copy(camera.position).sub(controls.target);
      var dist = THREE.MathUtils.clamp(
        offsetScratch.length() * factor,
        MIN_DISTANCE,
        MAX_DISTANCE,
      );
      offsetScratch.setLength(dist);
      camera.position.copy(controls.target).add(offsetScratch);
    }

    function resetView() {
      camera.position.copy(HOME_POSITION);
      controls.target.set(0, 0, 0);
      camera.lookAt(controls.target);
      controls.update();
    }

    // ============================================================
    // ANIMATION
    // ============================================================
    var clock = new THREE.Clock();
    var flickerTimer = 0;
    var rafId = 0;
    var frameCount = 0;
    var disposed = false;
    // One frame is drawn at creation; continuous animation is driven from
    // Python (jarvis_ui.orb_pump) because requestAnimationFrame AND timer
    // callbacks can freeze in this WebView2 build, especially when the
    // window sits on a non-interactive desktop. Pushing each frame via
    // evaluate_js() always executes, so the orb stays alive.

    function animate() {
      if (disposed) return;
      var t = clock.getElapsedTime();
      frameCount++;

      // Speaking state: jarvis's voice "comes from" the orb - it vibrates.
      var speaking =
        typeof document !== 'undefined' &&
        document.body &&
        document.body.classList &&
        document.body.classList.contains('speaking');
      var voicePulse = speaking ? 1 + Math.abs(Math.sin(t * 14)) * 0.28 : 1;

      // Outer shell rotation
      outerShell.rotation.y += 0.0015;
      outerShell.rotation.x = Math.sin(t * 0.08) * 0.05;

      // Panel group follows shell but with slight offset
      panelGroup.rotation.y += 0.0018;
      panelGroup.rotation.x = Math.sin(t * 0.08 + 0.5) * 0.04;

      // Secondary shell counter-rotates slowly
      shell2.rotation.y -= 0.001;
      shell2.rotation.z = Math.sin(t * 0.12) * 0.03;

      // Inner core — opposite, faster
      innerCore.rotation.y -= 0.005;
      innerCore.rotation.z += 0.002;
      innerCore.rotation.x = Math.cos(t * 0.1) * 0.08;

      // Innermost wireframe
      icoWire.rotation.x += 0.008;
      icoWire.rotation.y += 0.012;

      // Voice vibration from the orb core when Jarvis is talking
      if (speaking) {
        innerCore.rotation.x += Math.cos(t * 29) * 0.012;
        innerCore.rotation.z += Math.sin(t * 37) * 0.01;
        icoWire.rotation.x += Math.sin(t * 23) * 0.008;
        icoWire.rotation.y += Math.cos(t * 31) * 0.006;
        outerShell.rotation.z += Math.sin(t * 33) * 0.005;
        shell2.rotation.z += Math.cos(t * 21) * 0.004;
      }

      // Core pulse
      var wave1 = Math.sin(t * 1.2);
      var wave3 = Math.pow(Math.max(0, Math.sin(t * 0.4)), 5);
      var wave4 = Math.pow(Math.max(0, Math.sin(t * 0.7 + 2)), 8);
      var fadeOut = Math.pow(Math.max(0, Math.sin(t * 0.25)), 3);
      var surge = wave3 * 1.5 + wave4 * 2.0;
      var coreScale = (1 + surge + Math.sin(t * 5) * 0.05) * voicePulse;
      coreSphere.scale.setScalar(coreScale);
      var coreOpacity = Math.max(
        0,
        (0.08 + wave1 * 0.05 + surge * 0.2) * (1 - fadeOut * 0.95),
      );
      coreSphereMat.opacity = Math.min(0.6, coreOpacity + (speaking ? 0.08 : 0));
      glowSphere.scale.setScalar((1 + surge * 0.8) * voicePulse);
      glowSphereMat.opacity = Math.max(0, (0.03 + surge * 0.08) * (1 - fadeOut * 0.9));
      icoWire.scale.setScalar((1 + surge * 0.6) * voicePulse);
      icoWireMat.opacity = Math.min(1, 0.5 + surge * 0.4);

      // Debris orbits
      for (var di2 = 0; di2 < debris.length; di2++) {
        var db = debris[di2];
        var u = db.userData;
        var a = t * u.speed + u.phase;
        db.position.set(
          u.orbitR * Math.cos(a) * Math.cos(u.tiltX),
          u.orbitR * Math.sin(u.tiltX) * Math.sin(a * 0.8) + Math.sin(a * 0.3 + u.tiltZ) * 0.2,
          u.orbitR * Math.sin(a) * Math.cos(u.tiltZ),
        );
        db.rotation.x += 0.015;
        db.rotation.z += 0.01;
      }

      // Text drift
      var driftGroups = [
        [textOuter, 1],
        [textInner, 2],
        [textAmbient, 1.2],
      ];
      for (var gi = 0; gi < driftGroups.length; gi++) {
        var group = driftGroups[gi][0];
        var mult = driftGroups[gi][1];
        var kids = group.children;
        for (var ki = 0; ki < kids.length; ki++) {
          var sp = kids[ki];
          var su = sp.userData;
          su.theta += su.speed * mult;
          sp.position.set(
            su.r * Math.sin(su.phi) * Math.cos(su.theta),
            su.r * Math.cos(su.phi),
            su.r * Math.sin(su.phi) * Math.sin(su.theta),
          );
        }
      }

      // Scan rings sweeping
      var scanY1 = Math.sin(t * 0.4) * R1;
      scanRing1.position.y = scanY1;
      var scanS1 = Math.sqrt(Math.max(0, R1 * R1 - scanY1 * scanY1)) / R1;
      scanRing1.scale.set(scanS1, scanS1, 1);
      scanRing1.material.opacity = 0.2 * scanS1;

      var scanY2 = Math.sin(t * 0.6 + 2) * R3;
      scanRing2.position.y = scanY2;
      var scanS2 = Math.sqrt(Math.max(0, R3 * R3 - scanY2 * scanY2)) / R3;
      scanRing2.scale.set(scanS2, scanS2, 1);
      scanRing2.material.opacity = 0.15 * scanS2;

      // Dust rotation
      dustPoints.rotation.y += 0.0002;

      // Random flicker on some panels
      flickerTimer += 0.016;
      if (flickerTimer > 0.1) {
        flickerTimer = 0;
        var pkids = panelGroup.children;
        for (var pk = 0; pk < pkids.length; pk++) {
          if (Math.random() > 0.95) {
            pkids[pk].visible = !pkids[pk].visible;
          }
        }
      }

      // Bloom pulse (kept for reference; post-processing is disabled)
      // Chromatic aberration time (kept for reference; see above)

      // Gentle continuous auto-orbit (replaces the missing OrbitControls)
      rotateBy(AUTO_SPIN, 0);
      controls.update();
      renderer.render(scene, camera);
    }

    animate();

    // ---------- RESIZE ----------
    function onResize() {
      var w = container.clientWidth || 1;
      var h = container.clientHeight || 1;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    window.addEventListener("resize", onResize);

    // ---------- CLEANUP ----------
    function dispose() {
      disposed = true;
      clearInterval(rafId);
      window.removeEventListener("resize", onResize);
      if (controls.dispose) controls.dispose();
      scene.traverse(function (obj) {
        if (obj.geometry) obj.geometry.dispose();
        var mats = Array.isArray(obj.material) ? obj.material : [obj.material];
        for (var mm = 0; mm < mats.length; mm++) {
          var mat = mats[mm];
          if (!mat) continue;
          if (mat.map) mat.map.dispose();
          mat.dispose();
        }
      });
      if (renderer) renderer.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    }

    return {
      rotateBy: rotateBy,
      zoomBy: zoomBy,
      zoomIn: function () { zoomBy(0.65); },
      zoomOut: function () { zoomBy(1.55); },
      resetView: resetView,
      dispose: dispose,
      step: animate,
      frameCountLive: function () { return frameCount; },
      canvas: renderer.domElement,
      setMessage: function (text) {
        var s = String(text == null ? "" : text).trim();
        var cv = statusLabel.userData.canvas;
        var g = cv.getContext("2d");
        g.clearRect(0, 0, cv.width, cv.height);
        if (s) {
          g.font = "bold 56px Segoe UI, Arial, sans-serif";
          g.textAlign = "center";
          g.textBaseline = "middle";
          g.shadowColor = "rgba(255,170,48,0.9)";
          g.shadowBlur = 24;
          g.lineWidth = 8;
          g.strokeStyle = "rgba(10,20,35,0.9)";
          g.strokeText(s, cv.width / 2, cv.height / 2);
          g.fillStyle = "#ffcf7a";
          g.fillText(s, cv.width / 2, cv.height / 2);
        }
        statusLabel.userData.tex.needsUpdate = true;
        statusLabel.visible = !!s;
      },
    };
  }

  window.__orbDiag = function () {
    var handle = window.__orb;
    if (!handle) return { orb: false };
    var out = {};
    try {
      var gl = handle.canvas.getContext("webgl2") || handle.canvas.getContext("webgl");
      out.contextLost = gl ? gl.isContextLost() : null;
      out.frames = handle.frames;
      out.canvasW = handle.canvas.width;
      out.canvasH = handle.canvas.height;
      out.cssW = handle.canvas.clientWidth;
      out.cssH = handle.canvas.clientHeight;
      out.viewport = [window.innerWidth, window.innerHeight];
      if (gl && !out.contextLost) {
        var W = gl.drawingBufferWidth, H = gl.drawingBufferHeight;
        var px = new Uint8Array(4);
        gl.readPixels(W >> 1, H >> 1, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
        out.centerPixel = [px[0], px[1], px[2]];
      }
    } catch (e) {
      out.probeError = String(e);
    }
    return out;
  };
  window.__orbDiag.access = function () { return typeof window.__orb !== "undefined"; };

  window.createOrbScene = createOrbScene;
})();