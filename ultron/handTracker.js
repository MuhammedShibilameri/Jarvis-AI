/* ============================================================
   MediaPipe hand tracking for the orb (port of lib/handTracker.ts
   from SAGAR-TAMANG/ultron-by-sagar-builds, MIT).
   Exposes window.HandTracker. Requires the @mediapipe/tasks-vision
   global bundle to be loaded first.
   ============================================================ */

(function () {
  "use strict";

  var WASM_CDN = "/ultron/mediapipe";
  var MODEL_URL = "/ultron/mediapipe/hand_landmarker.task";

  // Landmark indices (MediaPipe hand model)
  var WRIST = 0;
  var THUMB_TIP = 4;
  var INDEX_TIP = 8;
  var MIDDLE_MCP = 9;

  // Pinch hysteresis: thumb-index distance relative to hand size
  var PINCH_ON = 0.32;
  var PINCH_OFF = 0.45;

  // How strongly hand movement rotates the orb (radians per normalized unit)
  var ROTATE_SPEED = 5.0;
  // Smoothing factor for grab-point tracking (0..1, higher = snappier)
  var SMOOTHING = 0.4;

  function dist2d(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  window.HandTracker = function (video, overlay, callbacks) {
    this.video = video;
    this.overlay = overlay;
    this.callbacks = callbacks;

    this.landmarker = null;
    this.stream = null;
    this.rafId = 0;
    this.running = false;
    this.lastVideoTime = -1;

    // keyed by handedness label so state survives re-ordering between frames
    this.handStates = new Map();
    this.prevMode = "idle";
    this.prevSpinGrab = null;
    this.prevZoomDist = null;
    this.lastStatus = { hands: 0, mode: "idle" };
  };

  window.HandTracker.prototype.start = async function () {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: "user" },
      audio: false,
    });
    this.video.srcObject = this.stream;
    await this.video.play();

    var fileset = await window.FilesetResolver.forVisionTasks(WASM_CDN);
    var options = {
      baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
      runningMode: "VIDEO",
      numHands: 2,
      minHandDetectionConfidence: 0.6,
      minHandPresenceConfidence: 0.6,
      minTrackingConfidence: 0.6,
    };
    try {
      this.landmarker = await window.HandLandmarker.createFromOptions(fileset, options);
    } catch (e) {
      // Some browsers/GPUs reject the GPU delegate - fall back to CPU
      console.log("hand tracker GPU failed, using CPU: " + e);
      options.baseOptions = { modelAssetPath: MODEL_URL, delegate: "CPU" };
      this.landmarker = await window.HandLandmarker.createFromOptions(fileset, options);
    }

    this.running = true;
    var self = this;
    var loop = function () {
      if (!self.running) return;
      self.rafId = requestAnimationFrame(loop);

      if (!self.landmarker || self.video.readyState < 2) return;
      if (self.video.currentTime === self.lastVideoTime) return;
      self.lastVideoTime = self.video.currentTime;

      var result = self.landmarker.detectForVideo(self.video, performance.now());
      var labels = [];
      for (var h = 0; h < result.handedness.length; h++) {
        var top = result.handedness[h][0];
        labels.push(top ? top.categoryName : "?");
      }
      self.processHands(result.landmarks, labels);
      self.drawOverlay(result.landmarks);
    };
    this._loop = loop;
    loop();
  };

  window.HandTracker.prototype.stop = function () {
    this.running = false;
    cancelAnimationFrame(this.rafId);
    if (this.landmarker && this.landmarker.close) this.landmarker.close();
    this.landmarker = null;
    if (this.stream) {
      this.stream.getTracks().forEach(function (t) { t.stop(); });
    }
    this.stream = null;
    this.video.srcObject = null;
    this.handStates.clear();
    this.prevMode = "idle";
    this.prevSpinGrab = null;
    this.prevZoomDist = null;
    var ctx = this.overlay.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, this.overlay.width, this.overlay.height);
    this.emitStatus({ hands: 0, mode: "idle" });
  };

  window.HandTracker.prototype.processHands = function (landmarks, labels) {
    var pinchedGrabs = [];
    var seen = new Set();
    var self = this;

    for (var i = 0; i < landmarks.length; i++) {
      var lm = landmarks[i];
      var label = labels[i];
      seen.add(label);

      var handScale = dist2d(lm[WRIST], lm[MIDDLE_MCP]);
      if (handScale < 1e-6) return;
      var pinchRatio = dist2d(lm[THUMB_TIP], lm[INDEX_TIP]) / handScale;

      // Mirrored so hand-right = screen-right from the user's perspective
      var raw = {
        x: 1 - (lm[THUMB_TIP].x + lm[INDEX_TIP].x) / 2,
        y: (lm[THUMB_TIP].y + lm[INDEX_TIP].y) / 2,
      };

      var state = this.handStates.get(label);
      if (!state) {
        state = { pinching: false, grab: raw };
        this.handStates.set(label, state);
      }

      // Hysteresis so the pinch doesn't flicker on/off at the threshold
      if (state.pinching && pinchRatio > PINCH_OFF) state.pinching = false;
      else if (!state.pinching && pinchRatio < PINCH_ON) state.pinching = true;

      state.grab = {
        x: state.grab.x + (raw.x - state.grab.x) * SMOOTHING,
        y: state.grab.y + (raw.y - state.grab.y) * SMOOTHING,
      };

      if (state.pinching) pinchedGrabs.push(state.grab);
    }

    // Drop state for hands that left the frame
    var keys = Array.from(this.handStates.keys());
    for (var k = 0; k < keys.length; k++) {
      if (!seen.has(keys[k])) this.handStates.delete(keys[k]);
    }

    var mode = pinchedGrabs.length >= 2 ? "zoom" : pinchedGrabs.length === 1 ? "spin" : "idle";

    // Reset reference points on any mode change to avoid jumps
    if (mode !== this.prevMode) {
      this.prevSpinGrab = null;
      this.prevZoomDist = null;
      this.prevMode = mode;
    }

    if (mode === "spin") {
      var grab = pinchedGrabs[0];
      if (this.prevSpinGrab) {
        var dx = grab.x - this.prevSpinGrab.x;
        var dy = grab.y - this.prevSpinGrab.y;
        if (Math.abs(dx) > 1e-4 || Math.abs(dy) > 1e-4) {
          this.callbacks.onRotate(dx * ROTATE_SPEED, dy * ROTATE_SPEED);
        }
      }
      this.prevSpinGrab = grab;
    } else if (mode === "zoom") {
      var d = Math.hypot(
        pinchedGrabs[0].x - pinchedGrabs[1].x,
        pinchedGrabs[0].y - pinchedGrabs[1].y,
      );
      if (this.prevZoomDist && d > 1e-4) {
        // Spread hands apart -> factor < 1 -> camera moves closer
        var factor = Math.min(1.18, Math.max(0.85, this.prevZoomDist / d));
        this.callbacks.onZoom(factor);
      }
      this.prevZoomDist = d;
    }

    this.emitStatus({ hands: landmarks.length, mode: mode });
  };

  window.HandTracker.prototype.emitStatus = function (status) {
    if (
      status.hands !== this.lastStatus.hands ||
      status.mode !== this.lastStatus.mode
    ) {
      this.lastStatus = status;
      this.callbacks.onStatus(status);
    }
  };

  window.HandTracker.prototype.drawOverlay = function (landmarks) {
    var ctx = this.overlay.getContext("2d");
    if (!ctx) return;
    var width = this.overlay.width;
    var height = this.overlay.height;
    ctx.clearRect(0, 0, width, height);

    for (var i = 0; i < landmarks.length; i++) {
      var lm = landmarks[i];
      var thumb = lm[THUMB_TIP];
      var index = lm[INDEX_TIP];
      // Overlay canvas sits on the mirrored video preview, so mirror x here too
      var tx = (1 - thumb.x) * width;
      var ty = thumb.y * height;
      var ix = (1 - index.x) * width;
      var iy = index.y * height;

      var handScale = dist2d(lm[WRIST], lm[MIDDLE_MCP]);
      var pinched = handScale > 1e-6 && dist2d(thumb, index) / handScale < PINCH_ON;

      ctx.strokeStyle = pinched ? "#ffcc66" : "rgba(255,170,48,0.5)";
      ctx.lineWidth = pinched ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(ix, iy);
      ctx.stroke();

      ctx.fillStyle = pinched ? "#ffcc66" : "rgba(255,170,48,0.7)";
      var dots = [[tx, ty], [ix, iy]];
      for (var d = 0; d < dots.length; d++) {
        ctx.beginPath();
        ctx.arc(dots[d][0], dots[d][1], pinched ? 5 : 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  };
})();