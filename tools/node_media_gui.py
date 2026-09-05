"""Audio, capture and VRChat controls for the Windows app."""
from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


class MediaControls:
    def _init_media_controls(self):
        self.media_settings = {}
        defaults = {"game_vision_enabled": False, "audio_listen_enabled": False,
                    "windows_tts_enabled": True, "vision_interval_seconds": 10,
                    "audio_record_seconds": 5, "vrchat_osc_enabled": False,
                    "vrchat_send_port": 9000, "vrchat_receive_port": 9001, "tesseract_path": ""}
        for key, value in defaults.items():
            cls = tk.BooleanVar if isinstance(value, bool) else tk.IntVar if isinstance(value, int) else tk.StringVar
            self.media_settings[key] = cls(value=self.config_data.get(key, value))
        self.input_device_var = tk.StringVar(value=self.config_data.get("audio_input_label", "Select input"))
        self.output_device_var = tk.StringVar(value=self.config_data.get("audio_output_label", "Default output"))
        self._audio_inputs = {}
        self._audio_outputs = {"Default output": None}
        self.tts_text_var = tk.StringVar(value="Hello from NekoSuneAI on the Pi.")
        self.media_status_var = tk.StringVar(value="Node stopped")
        self.osc_status_var = tk.StringVar(value="OSC disabled")
        self.chatbox_var = tk.StringVar()
        self.avatar_parameter_var = tk.StringVar(value="VRCEmote")
        self.avatar_value_var = tk.StringVar(value="1")
        self._tool_busy = False

    def _build_media_page(self):
        page = ttk.Frame(self.page_host, style="App.TFrame")
        self.pages["media"] = page
        audio = self._card(page, "Windows audio / Pi speech")
        audio.columnconfigure(1, weight=1)
        for row, (label, variable, name) in enumerate((("Microphone / loopback", self.input_device_var, "audio_input_combo"), ("Playback output", self.output_device_var, "audio_output_combo"))):
            ttk.Label(audio, text=label, style="Body.TLabel").grid(row=row, column=0, padx=22, pady=7, sticky="w")
            combo = ttk.Combobox(audio, textvariable=variable, state="readonly", width=24, style="Modern.TCombobox")
            combo.grid(row=row, column=1, padx=(0, 22), pady=7, sticky="ew")
            setattr(self, name, combo)
        actions = ttk.Frame(audio, style="Card.TFrame")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", padx=22, pady=8)
        ttk.Button(actions, text="Refresh devices", command=self._refresh_audio_devices, style="Secondary.TButton").pack(side="left")
        ttk.Button(actions, text="Record once", command=lambda: self._run_node_tool(lambda agent: agent.media.listen()), style="Secondary.TButton").pack(side="left", padx=6)
        ttk.Button(actions, text="Stop audio", command=self._stop_audio, style="Danger.TButton").pack(side="right")
        ttk.Checkbutton(audio, text="Continuous listening", variable=self.media_settings["audio_listen_enabled"], style="Modern.TCheckbutton").grid(row=3, column=0, columnspan=2, sticky="w", padx=22)
        ttk.Checkbutton(audio, text="Play game narration on Windows", variable=self.media_settings["windows_tts_enabled"], style="Modern.TCheckbutton").grid(row=4, column=0, columnspan=2, sticky="w", padx=22)
        ttk.Label(audio, text="Recording seconds", style="Body.TLabel").grid(row=5, column=0, sticky="w", padx=22, pady=8)
        ttk.Spinbox(audio, from_=1, to=15, width=5, textvariable=self.media_settings["audio_record_seconds"]).grid(row=5, column=1, sticky="w")
        self._field(audio, "TTS text", self.tts_text_var, 6)
        ttk.Button(audio, text="Speak through Pi", command=self._test_tts, style="Primary.TButton").grid(row=7, column=1, sticky="e", padx=22, pady=8)
        vision = self._card(page, "Gameplay capture")
        ttk.Checkbutton(vision, text="Send gameplay frames to Pi", variable=self.media_settings["game_vision_enabled"], style="Modern.TCheckbutton").pack(anchor="w", padx=22, pady=8)
        duration = ttk.Frame(vision, style="Card.TFrame")
        duration.pack(fill="x", padx=22, pady=8)
        ttk.Label(duration, text="Analysis interval (seconds)", style="Muted.TLabel").pack(side="left")
        ttk.Spinbox(duration, from_=5, to=120, width=5, textvariable=self.media_settings["vision_interval_seconds"]).pack(side="left", padx=8)
        buttons = ttk.Frame(vision, style="Card.TFrame")
        buttons.pack(fill="x", padx=22, pady=8)
        ttk.Button(buttons, text="Analyse in 3 seconds", command=self._analyse_game, style="Secondary.TButton").pack(side="left")
        ttk.Button(buttons, text="Select Tesseract", command=self._select_tesseract, style="Secondary.TButton").pack(side="left", padx=6)
        ttk.Button(vision, text="Apply media settings", command=self._apply_media_settings, style="Primary.TButton").pack(anchor="e", padx=22, pady=8)
        self.capture_preview = ttk.Label(vision, style="Body.TLabel", text="No captured frame")
        self.capture_preview.pack(fill="x", padx=22, pady=8)
        self.media_result = self._text_output(vision)
        self.media_result.pack(fill="x", padx=22, pady=8)
        ttk.Label(vision, textvariable=self.media_status_var, style="Muted.TLabel", wraplength=500).pack(anchor="w", padx=22, pady=8)

    @staticmethod
    def _text_output(parent):
        return tk.Text(parent, width=40, height=8, wrap="word", bg="#0f151c", fg="#f4f7fb", relief="flat", state="disabled")

    def _build_vrchat_page(self):
        page = ttk.Frame(self.page_host, style="App.TFrame")
        self.pages["vrchat"] = page
        osc = self._card(page, "VRChat OSC")
        osc.columnconfigure(1, weight=1)
        ttk.Checkbutton(osc, text="Enable local OSC on node start", variable=self.media_settings["vrchat_osc_enabled"], style="Modern.TCheckbutton").grid(row=0, column=0, columnspan=2, sticky="w", padx=22, pady=8)
        self._field(osc, "VRChat input port", self.media_settings["vrchat_send_port"], 1)
        self._field(osc, "VRChat output port", self.media_settings["vrchat_receive_port"], 2)
        actions = ttk.Frame(osc, style="Card.TFrame")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", padx=22, pady=8)
        ttk.Button(actions, text="Save", command=self.save, style="Primary.TButton").pack(side="left")
        ttk.Button(actions, text="Arm OSC", command=self._arm_osc, style="Secondary.TButton").pack(side="left", padx=6)
        ttk.Button(actions, text="Stop / disarm", command=self._stop_osc, style="Danger.TButton").pack(side="right")
        motion = ttk.Frame(osc, style="Card.TFrame")
        motion.grid(row=4, column=0, columnspan=2, sticky="ew", padx=22, pady=8)
        for column, (label, name, value) in enumerate((("Forward", "Vertical", 1), ("Back", "Vertical", -1), ("Left", "Horizontal", -1), ("Right", "Horizontal", 1), ("Jump", "Jump", 1))):
            motion.columnconfigure(column, weight=1)
            ttk.Button(motion, text=label, command=lambda n=name, v=value: self._run_node_tool(lambda agent: self._osc(agent).pulse(n, v)), style="Secondary.TButton").grid(row=0, column=column, sticky="ew", padx=2)
        self._field(osc, "Chatbox text", self.chatbox_var, 5)
        ttk.Button(osc, text="Send chatbox", command=self._send_chatbox, style="Primary.TButton").grid(row=6, column=1, sticky="e", padx=22, pady=8)
        self._field(osc, "Avatar parameter", self.avatar_parameter_var, 7)
        self._field(osc, "Value (JSON)", self.avatar_value_var, 8)
        ttk.Button(osc, text="Set parameter", command=self._set_avatar_parameter, style="Primary.TButton").grid(row=9, column=1, sticky="e", padx=22, pady=8)
        ttk.Label(osc, textvariable=self.osc_status_var, style="Muted.TLabel", wraplength=500).grid(row=10, column=0, columnspan=2, sticky="w", padx=22, pady=8)
        self.osc_parameters = self._text_output(osc)
        self.osc_parameters.grid(row=11, column=0, columnspan=2, sticky="ew", padx=22, pady=8)

    def _media_values(self):
        values = {key: variable.get() for key, variable in self.media_settings.items()}
        for key, low, high in (("vision_interval_seconds", 5, 120), ("audio_record_seconds", 1, 15), ("vrchat_send_port", 1, 65535), ("vrchat_receive_port", 1, 65535)):
            if not low <= int(values[key]) <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
        values["audio_input_device"] = self._audio_inputs.get(self.input_device_var.get(), self.config_data.get("audio_input_device"))
        values["audio_output_device"] = self._audio_outputs.get(self.output_device_var.get(), self.config_data.get("audio_output_device"))
        values["audio_input_label"] = self.input_device_var.get()
        values["audio_output_label"] = self.output_device_var.get()
        return values

    def _apply_media_settings(self):
        if self.save() and self.agent is not None:
            self.agent.config.update(self._media_values())
            self.status_var.set("Media settings applied; OSC port changes require node restart")

    def _refresh_audio_devices(self):
        from nekosuneai.node_audio import NodeAudio
        try:
            devices = NodeAudio.devices()
            self._audio_inputs = {f"{x['index']}: {x['name']}": x["index"] for x in devices["inputs"]}
            self._audio_outputs = {"Default output": None, **{f"{x['index']}: {x['name']}": x["index"] for x in devices["outputs"]}}
            self.audio_input_combo["values"] = list(self._audio_inputs)
            self.audio_output_combo["values"] = list(self._audio_outputs)
            self.status_var.set(f"Found {len(self._audio_inputs)} inputs and {len(self._audio_outputs) - 1} outputs")
        except Exception as exc:
            messagebox.showerror("Audio devices", str(exc))

    def _run_node_tool(self, operation, delay=0):
        if self._tool_busy:
            self.status_var.set("A local tool is already running")
            return
        if self.agent is None or self.agent._stop.is_set() or not self.agent_thread or not self.agent_thread.is_alive():
            messagebox.showerror("Windows node", "Start the paired node on the Gaming Node page first.")
            return
        try:
            self.agent.config.update(self._media_values())
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Media settings", str(exc))
            return
        self._tool_busy = True
        agent = self.agent
        self.status_var.set("Switch to the game window; capture starts in 3 seconds" if delay else "Processing...")
        def worker():
            try:
                if delay and agent._stop.wait(delay):
                    return
                result = operation(agent)
                self.after(0, lambda value=result: self._tool_done(value))
            except Exception as exc:
                self.after(0, lambda error=str(exc): self._tool_done(error))
            finally:
                self._tool_busy = False
        threading.Thread(target=worker, daemon=True).start()

    def _tool_done(self, result):
        self.status_var.set(str(result)[:160])
        self.media_status_var.set(str(result)[:350])

    def _analyse_game(self):
        def operation(agent):
            capture = agent.vision.capture(detailed=True, image_limit=500_000)
            if capture.get("screenshot_jpeg_base64"):
                self.after(0, lambda: self._preview_capture(capture["screenshot_jpeg_base64"]))
            return agent.media.vision(capture)
        self._run_node_tool(operation, delay=3)

    def _preview_capture(self, encoded):
        import base64
        import io
        from PIL import Image, ImageTk
        image = Image.open(io.BytesIO(base64.b64decode(encoded)))
        image.thumbnail((min(500, max(200, self.page_host.winfo_width() - 44)), 280))
        self._capture_photo = ImageTk.PhotoImage(image)
        self.capture_preview.configure(image=self._capture_photo, text="")

    def _select_tesseract(self):
        selected = filedialog.askopenfilename(title="Select tesseract.exe", filetypes=[("Tesseract executable", "*.exe")])
        if selected:
            self.media_settings["tesseract_path"].set(selected)

    def _test_tts(self):
        text = self.tts_text_var.get().strip()
        self._run_node_tool(lambda agent: agent.media.speak(text))

    def _stop_audio(self):
        self.media_settings["audio_listen_enabled"].set(False)
        self.media_settings["windows_tts_enabled"].set(False)
        if self.agent:
            self.agent.config["audio_listen_enabled"] = False
            self.agent.config["windows_tts_enabled"] = False
            self.agent.media.cancel_audio()
        self.status_var.set("Audio stopped")

    @staticmethod
    def _osc(agent):
        if agent is None or agent.vrchat is None:
            raise RuntimeError("Select the VRChat profile, enable OSC, then restart the node")
        return agent.vrchat

    def _arm_osc(self):
        try:
            self._osc(self.agent).arm()
            self.status_var.set("VRChat OSC armed")
        except (RuntimeError, PermissionError) as exc:
            messagebox.showerror("VRChat OSC", str(exc))

    def _stop_osc(self):
        if self.agent and self.agent.vrchat:
            self.agent.vrchat.stop_input()
        self.status_var.set("VRChat OSC disarmed")

    def _send_chatbox(self):
        text = self.chatbox_var.get()
        self._run_node_tool(lambda agent: self._osc(agent).chatbox(text))

    def _set_avatar_parameter(self):
        try:
            name, value = self.avatar_parameter_var.get(), json.loads(self.avatar_value_var.get())
        except ValueError as exc:
            messagebox.showerror("Avatar parameter", str(exc))
            return
        self._run_node_tool(lambda agent: self._osc(agent).avatar_parameter(name, value))

    @staticmethod
    def _set_readonly_text(widget, text):
        if widget.get("1.0", "end-1c") != text:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.configure(state="disabled")

    def _refresh_media_status(self):
        if self.agent:
            state = self.agent.media.snapshot()
            self._set_readonly_text(self.media_result, "Gameplay:\n" + state.get("description", "") + "\n\nTranscript:\n" + state.get("transcript", ""))
            if state.get("error"):
                self.media_status_var.set(state["error"])
            if self.agent.vrchat:
                osc = self.agent.vrchat.status()
                self.osc_status_var.set(("Armed" if osc["armed"] else "Disarmed") + (" / receiving OSC" if osc["receiving"] else " / no recent OSC data"))
                self._set_readonly_text(self.osc_parameters, json.dumps(osc, indent=2))
        self.after(1000, self._refresh_media_status)

    def _close_app(self):
        if self.agent:
            self.agent.stop()
        self.destroy()
