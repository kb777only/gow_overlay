"""setup_gui.py - a small settings window for the damage overlay.

Launched with `python gow_overlay.py --setup`. Every change is written to
settings.json immediately, and a running overlay live-reloads it within a frame,
so you can tune the look while watching it. Pure tkinter (standard library)."""
import os
import subprocess
import sys

import tkinter as tk
from tkinter import ttk, colorchooser, filedialog, messagebox

from settings import S


def _get(path):
    d = S.data
    for k in path:
        d = d[k]
    return d


def _set(path, val):
    d = S.data
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = val
    S.save()


def _hex(rgb):
    return "#%02x%02x%02x" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


class SetupApp:
    def __init__(self, root):
        self.root = root
        root.title("GoW Damage Overlay — Settings")
        root.geometry("440x560")
        root.minsize(420, 480)
        self._build()

    # ---- control builders -------------------------------------------------
    def slider(self, parent, label, path, lo, hi, is_int=False):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=10, pady=4)
        ttk.Label(row, text=label, width=18, anchor="w").pack(side="left")
        cur = _get(path)
        valbl = ttk.Label(row, width=6, anchor="e")

        def on_change(v):
            x = float(v)
            if is_int:
                x = int(round(x))
            _set(path, x)
            valbl.config(text=(str(int(x)) if is_int else f"{x:.2f}"))

        sc = ttk.Scale(row, from_=lo, to=hi, value=cur, command=on_change)
        sc.pack(side="left", fill="x", expand=True, padx=6)
        valbl.config(text=(str(int(cur)) if is_int else f"{cur:.2f}"))
        valbl.pack(side="left")

    def check(self, parent, label, path):
        var = tk.BooleanVar(value=bool(_get(path)))

        def on():
            _set(path, bool(var.get()))

        ttk.Checkbutton(parent, text=label, variable=var, command=on).pack(
            anchor="w", padx=12, pady=3)

    def color_row(self, parent, label, path):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=10, pady=3)
        ttk.Label(row, text=label, width=14, anchor="w").pack(side="left")
        sw = tk.Label(row, width=5, background=_hex(_get(path)), relief="sunken")
        sw.pack(side="left", padx=6)

        def pick():
            c = colorchooser.askcolor(color=_hex(_get(path)), parent=self.root)
            if c and c[0]:
                rgb = [int(c[0][0]), int(c[0][1]), int(c[0][2])]
                _set(path, rgb)
                sw.config(background=_hex(rgb))

        ttk.Button(row, text="Pick…", command=pick).pack(side="left")

    # ---- layout -----------------------------------------------------------
    def _build(self):
        for w in self.root.winfo_children():
            w.destroy()
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        # Numbers tab
        t = ttk.Frame(nb); nb.add(t, text="Numbers")
        self.slider(t, "Base size", ("numbers", "size_base"), 8, 60, True)
        self.slider(t, "Size / damage", ("numbers", "size_per_damage"), 0.0, 1.2)
        self.slider(t, "Lifetime (s)", ("numbers", "ttl"), 0.4, 4.0)
        self.slider(t, "Rise (px)", ("numbers", "rise"), 0, 140, True)
        self.slider(t, "Tracking lerp", ("numbers", "anchor_lerp"), 0.05, 1.0)
        self.slider(t, "Head offset (px)", ("numbers", "head_offset"), 0, 120, True)
        self.slider(t, "Fade start", ("numbers", "fade_start"), 0.0, 0.95)
        self.slider(t, "Pop strength", ("numbers", "pop"), 0.0, 1.5)
        self.slider(t, "Max damage shown", ("numbers", "max_damage"), 50, 5000, True)

        # Epic FX tab
        t = ttk.Frame(nb); nb.add(t, text="Epic FX")
        self.slider(t, "Epic min dmg", ("epic", "min_damage"), 0, 120, True)
        self.slider(t, "Epic full dmg", ("epic", "full_damage"), 10, 200, True)
        self.check(t, "Screenshake", ("epic", "shake_enabled"))
        self.slider(t, "Shake amount", ("epic", "shake_amount"), 0.0, 3.0)
        self.check(t, "Edge flash", ("epic", "flash_enabled"))
        self.slider(t, "Flash amount", ("epic", "flash_amount"), 0.0, 3.0)
        self.check(t, "Shockwave ring", ("epic", "ring_enabled"))
        self.check(t, "White-hot pop", ("epic", "whitehot_enabled"))
        self.slider(t, "Epic extra pop", ("epic", "extra_pop"), 0.0, 1.5)
        self.slider(t, "Epic extra linger", ("epic", "extra_ttl"), 0.0, 1.5)

        # Animations tab
        t = ttk.Frame(nb); nb.add(t, text="Animations")
        self.check(t, "Gradient-filled digits", ("anim", "gradient_enabled"))
        self.check(t, "Heat shimmer", ("anim", "shimmer_enabled"))
        self.slider(t, "Shimmer speed", ("anim", "shimmer_speed"), 0.0, 3.0)
        self.check(t, "Flames on big hits", ("anim", "fire_enabled"))
        self.slider(t, "Flame amount", ("anim", "fire_amount"), 0.2, 1.5)
        self.check(t, "Ember sparks", ("anim", "sparks_enabled"))
        self.slider(t, "Spark amount", ("anim", "sparks_amount"), 0.0, 2.0)
        self.check(t, "Fireball burst", ("anim", "fireball_enabled"))

        # Colors tab
        t = ttk.Frame(nb); nb.add(t, text="Colors")
        ttk.Label(t, text="Damage → colour ramp", anchor="w").pack(
            anchor="w", padx=10, pady=(8, 2))
        tiers = S.data["colors"]
        for i, (thr, _rgb) in enumerate(tiers):
            lo = 0 if i == 0 else tiers[i - 1][0]
            rng = f"{lo}+" if thr >= 100000 else f"{lo}–{thr}"
            self.color_row(t, f"dmg {rng}", ("colors", i, 1))

        # Tracking tab
        t = ttk.Frame(nb); nb.add(t, text="Tracking")
        ttk.Label(t, text="Enemy detection (advanced)", anchor="w").pack(
            anchor="w", padx=10, pady=(8, 2))
        self.slider(t, "Scan period (s)", ("tracking", "scan_period"), 0.1, 1.5)
        self.slider(t, "Near-player dist", ("tracking", "near_player_dist"), 100, 4000, True)
        self.slider(t, "Creature min HP", ("tracking", "creature_min_hp"), 3, 50, True)
        self.slider(t, "Creature max HP", ("tracking", "creature_max_hp"), 30, 5000, True)

        # preset sharing row
        pr = ttk.Frame(self.root); pr.pack(fill="x", padx=8, pady=(0, 2))
        ttk.Label(pr, text="Presets:", foreground="#666").pack(side="left")
        ttk.Button(pr, text="Import…", command=self._import).pack(side="left", padx=(6, 0))
        ttk.Button(pr, text="Export…", command=self._export).pack(side="left", padx=6)

        # bottom bar
        bar = ttk.Frame(self.root); bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(bar, text="changes apply live to a running overlay",
                  foreground="#666").pack(side="left")
        ttk.Button(bar, text="Reset", command=self._reset).pack(side="right")
        ttk.Button(bar, text="Open JSON", command=self._open_json).pack(side="right", padx=6)

    def _reset(self):
        S.reset()
        self._build()

    _FILETYPES = [("GoW overlay preset", "*.json"), ("All files", "*.*")]

    def _export(self):
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export settings preset",
            defaultextension=".json", initialfile="gow-overlay-preset.json",
            filetypes=self._FILETYPES)
        if not path:
            return
        try:
            S.export_to(path)
        except OSError as e:
            messagebox.showerror("Export failed", str(e), parent=self.root)
            return
        messagebox.showinfo("Preset exported",
                            f"Saved to:\n{path}\n\nShare the file - others load it "
                            "with Import.", parent=self.root)

    def _import(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="Import settings preset",
            filetypes=self._FILETYPES)
        if not path:
            return
        try:
            S.import_from(path)
        except Exception as e:
            messagebox.showerror("Import failed",
                                 f"Could not load preset:\n{e}", parent=self.root)
            return
        self._build()      # show the imported values (a running overlay live-reloads)

    def _open_json(self):
        if sys.platform == "win32":
            try:
                os.startfile(S.path)
            except Exception:
                subprocess.Popen(["notepad", S.path])
        else:
            subprocess.Popen(["xdg-open", S.path])


def main():
    import respath
    root = tk.Tk(className="gow_overlay-setup")
    respath.set_tk_icon(root)
    SetupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
