# -*- coding: utf-8 -*-
"""Deactivate Zero Volume Mesh - Omniverse Script Editor

부피가 0에 가까운 degenerate 메시를 탐지하여 active=false 처리합니다.

부피 계산:
  삼각형 면 기반 signed volume (발산 정리):
  V = (1/6) * Σ (v1 · (v2 × v3))
  절댓값이 volume_threshold 이하면 zero-volume으로 판정

주의:
  - open mesh (구멍 있는 메시)는 signed volume이 부정확할 수 있음
  - flat mesh(판 형태)도 zero-volume으로 탐지될 수 있음
  - Dry Run으로 먼저 확인 권장

Dry Run: 탐지 결과만 로그 출력
Run    : 실제로 active=false 처리
"""

import numpy as np
import omni.usd
import omni.ui as ui
from pxr import Usd, UsdGeom

# ─────────────────────────── helpers ────────────────────────────────────────

def _get_mesh_data(prim):
    mesh = UsdGeom.Mesh(prim)
    pts_attr = mesh.GetPointsAttr()
    idx_attr = mesh.GetFaceVertexIndicesAttr()
    cnt_attr = mesh.GetFaceVertexCountsAttr()

    if not (pts_attr and pts_attr.HasValue() and
            idx_attr and idx_attr.HasValue() and
            cnt_attr and cnt_attr.HasValue()):
        return None, None, None

    pts  = pts_attr.Get()
    idxs = list(idx_attr.Get())
    cnts = list(cnt_attr.Get())
    if not pts or not idxs or not cnts:
        return None, None, None

    return (
        np.array([[float(p[0]), float(p[1]), float(p[2])] for p in pts]),
        idxs,
        cnts,
    )


def _signed_volume(pts, idxs, cnts):
    """삼각형 fan 기반 signed volume 계산. quad 이상 면도 fan 분할 처리."""
    total = 0.0
    offset = 0
    for cnt in cnts:
        face = idxs[offset:offset + cnt]
        offset += cnt
        if cnt < 3:
            continue
        v0 = pts[face[0]]
        for i in range(1, cnt - 1):
            v1 = pts[face[i]]
            v2 = pts[face[i + 1]]
            total += float(np.dot(v0, np.cross(v1, v2)))
    return abs(total) / 6.0

# ─────────────────────────── main process ───────────────────────────────────

def run_deactivate(vol_t, dry_run, log_fn):
    ctx   = omni.usd.get_context()
    stage = ctx.get_stage()
    if stage is None:
        log_fn("[ERROR] No stage open.")
        return 0, 0

    meshes = [p for p in stage.Traverse() if p.IsActive() and p.IsA(UsdGeom.Mesh)]
    log_fn(f"{len(meshes)} active mesh(es) found")

    deactivated = skipped = 0

    for prim in meshes:
        path_str = prim.GetPath().pathString
        pts, idxs, cnts = _get_mesh_data(prim)

        if pts is None:
            skipped += 1
            continue

        try:
            vol = _signed_volume(pts, idxs, cnts)
        except Exception:
            skipped += 1
            continue

        if vol <= vol_t:
            if dry_run:
                log_fn(f"  [DRY/ZERO] {path_str}  vol={vol:.6f}")
            else:
                prim.SetActive(False)
                log_fn(f"  [ZERO] {path_str}  vol={vol:.6f}")
            deactivated += 1
        else:
            skipped += 1

    mode = "DRY RUN" if dry_run else "DEACTIVATED"
    log_fn(f"Done ({mode}): {deactivated} zero-volume / {skipped} normal or skipped")
    return deactivated, skipped

# ───────────────────────────────── UI ────────────────────────────────────────

FONT_SCALE = 1.4
BTN_H      = 36
FIELD_H    = 28
LABEL_W    = 240
C_BG       = 0xFF1E1E1E
C_HEADER   = 0xFF2D2D2D
C_ACCENT   = 0xFF76B900
C_BTN      = 0xFF444444
C_BTN_RUN  = 0xFFCC4444
C_BTN_DRY  = 0xFF2255AA
C_TEXT     = 0xFFDDDDDD
C_DIM      = 0xFF888888
C_LOG_BG   = 0xFF151515

_window = None

def _make_window():
    global _window
    if _window:
        _window.destroy()

    _window = ui.Window("Deactivate Zero Volume Mesh", width=520, height=460,
                        flags=ui.WINDOW_FLAGS_NO_SCROLLBAR)

    with _window.frame:
        with ui.ZStack():
            ui.Rectangle(style={"background_color": C_BG})
            with ui.VStack(spacing=0):

                with ui.ZStack(height=40):
                    ui.Rectangle(style={"background_color": C_HEADER})
                    with ui.HStack():
                        ui.Spacer(width=12)
                        ui.Label("Deactivate Zero Volume Mesh",
                                 style={"color": C_ACCENT, "font_size": 14 * FONT_SCALE},
                                 width=0)
                        ui.Spacer()

                ui.Spacer(height=10)

                with ui.HStack(height=20):
                    ui.Spacer(width=12)
                    ui.Label("Threshold",
                             style={"color": C_DIM, "font_size": 11 * FONT_SCALE})
                ui.Spacer(height=4)

                with ui.HStack(height=FIELD_H, spacing=6):
                    ui.Spacer(width=12)
                    ui.Label("Volume threshold (abs signed vol <=)", width=LABEL_W,
                             style={"color": C_TEXT, "font_size": 13 * FONT_SCALE})
                    m_vol = ui.FloatDrag(min=0.0, max=1000.0, step=0.001).model
                    m_vol.set_value(0.001)
                    ui.Spacer(width=12)

                ui.Spacer(height=16)

                log_lines = []
                log_ref   = [None]

                def _append(msg):
                    log_lines.append(msg)
                    if log_ref[0]:
                        log_ref[0].text = "\n".join(log_lines[-60:])

                with ui.HStack(height=BTN_H, spacing=8):
                    ui.Spacer(width=12)

                    def _run_dry():
                        log_lines.clear()
                        if log_ref[0]: log_ref[0].text = ""
                        run_deactivate(
                            vol_t=m_vol.get_value_as_float(),
                            dry_run=True,
                            log_fn=_append,
                        )

                    def _run_deactivate():
                        log_lines.clear()
                        if log_ref[0]: log_ref[0].text = ""
                        run_deactivate(
                            vol_t=m_vol.get_value_as_float(),
                            dry_run=False,
                            log_fn=_append,
                        )

                    ui.Button("Dry Run", height=BTN_H, clicked_fn=_run_dry,
                              style={"background_color": C_BTN_DRY,
                                     "color": C_TEXT,
                                     "font_size": 12 * FONT_SCALE})

                    ui.Button("Deactivate", height=BTN_H, clicked_fn=_run_deactivate,
                              style={"background_color": C_BTN_RUN,
                                     "color": C_TEXT,
                                     "font_size": 13 * FONT_SCALE})

                    def _clear_log():
                        log_lines.clear()
                        if log_ref[0]: log_ref[0].text = ""

                    ui.Button("Clear Log", height=BTN_H, clicked_fn=_clear_log,
                              style={"background_color": C_BTN,
                                     "color": C_TEXT,
                                     "font_size": 12 * FONT_SCALE})
                    ui.Spacer(width=12)

                ui.Spacer(height=8)

                with ui.ZStack():
                    ui.Rectangle(style={"background_color": C_LOG_BG})
                    with ui.ScrollingFrame(
                        horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                        vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
                    ):
                        with ui.VStack():
                            ui.Spacer(height=4)
                            with ui.HStack():
                                ui.Spacer(width=8)
                                log_ref[0] = ui.Label(
                                    "", word_wrap=True,
                                    style={"color": C_DIM,
                                           "font_size": 11 * FONT_SCALE})
                                ui.Spacer(width=8)

_make_window()
