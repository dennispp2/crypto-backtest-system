"""Exchange-inspired dashboard layout; presentation only.

Inputs: Tk variables populated by the existing snapshot presenter.
Outputs: local widgets, navigation and help; no trading decisions.
Updated 2026-09-06.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
import customtkinter as ctk
from PIL import Image

from ui_components import (
    UI_COLORS, UI_FONT, AllocationBar, Button, Card, Label, Progress,
    SmoothScrollPage, configure_theme, font, frame, wrapping_label,
)


class DashboardLayout:
    def _styles(self):
        configure_theme(self)

    def _layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self._sidebar()
        self.main = frame(self)
        self.main.grid(row=0, column=1, sticky="nsew", padx=(24, 20), pady=(24, 14))
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(3, weight=1)
        self._header()
        self._notice()
        self.host = frame(self.main)
        self.host.grid(row=3, column=0, sticky="nsew", pady=(18, 0))
        self.host.grid_columnconfigure(0, weight=1)
        self.host.grid_rowconfigure(0, weight=1)
        self.pages = {}
        overview = SmoothScrollPage(self.host)
        self.pages["資產總覽"] = overview
        self.overview_page = overview
        self._overview(overview.content)
        self._reports()
        self._execution_report()
        self._audit()
        self._ai_page()
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        footer = frame(self.main)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.footer_var = tk.StringVar(value="正在讀取紙上帳本…")
        Label(footer, textvariable=self.footer_var, size=12, color="muted").pack(side="left")
        Label(footer, textvariable=self.vars["current_time"], size=12, color="muted",
              number=True).pack(side="right")
        self.show_page("資產總覽")
        self.bind("<F5>", lambda _: self.refresh_dashboard())
        self.bind("<Control-Key-1>", lambda _: self.show_page("資產總覽"))
        self.bind("<Control-Key-2>", lambda _: self.show_page("白話報告"))
        self.bind("<Control-Key-3>", lambda _: self.show_page("原始資料"))

    def _sidebar(self):
        side = ctk.CTkFrame(self, width=184, corner_radius=0, fg_color=UI_COLORS["sidebar"])
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(4, weight=1)
        brand = frame(side)
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(28, 28))
        icon_path = Path(__file__).resolve().parent / "assets" / "bitcoin_app_icon.png"
        if icon_path.is_file():
            with Image.open(icon_path) as source:
                self.brand_image = ctk.CTkImage(light_image=source.copy(), dark_image=source.copy(), size=(32, 32))
            ctk.CTkLabel(brand, text="", image=self.brand_image, width=32, height=32).pack(anchor="w")
        Label(brand, "Crypto Forward", size=19, bold=True, number=True).pack(anchor="w", pady=(12, 3))
        Label(brand, "加密貨幣前瞻監控", size=12, color="muted").pack(anchor="w")
        nav = frame(side)
        nav.grid(row=1, column=0, sticky="ew", padx=12)
        self.nav_buttons = {}
        for title in ("資產總覽", "白話報告", "執行摘要", "AI 決策", "原始資料"):
            button = Button(nav, title, lambda name=title: self.show_page(name),
                            width=160, anchor="w", border_spacing=16)
            button.configure(fg_color="transparent", text_color=UI_COLORS["muted"])
            button.pack(fill="x", pady=3)
            self.nav_buttons[title] = button
        Button(nav, "歷史紀錄", self.open_history, width=160, anchor="w",
               border_spacing=16).pack(fill="x", pady=(18, 3))
        utilities = frame(side)
        utilities.grid(row=5, column=0, sticky="ew", padx=12, pady=16)
        Button(utilities, "使用說明", self.show_help, width=160).pack(fill="x", pady=4)
        self.tools_button = Button(utilities, "工具與設定  ⌄", self.show_tools, width=160)
        self.tools_button.pack(fill="x", pady=4)
        Label(utilities, "僅紙上模擬 · 不會下單", size=12, color="muted").pack(pady=(20, 0))
        Label(utilities, "V3.10＋AI  /  V3.10", size=12, color="muted", number=True).pack(pady=(4, 0))

    def _header(self):
        header = frame(self.main)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        identity = frame(header)
        identity.grid(row=0, column=0, sticky="w")
        self.page_title = Label(identity, "資產總覽", size=25, bold=True)
        self.page_title.pack(anchor="w")
        Label(identity, "追蹤資產配置，掌握模型與市場狀態", size=13, color="muted").pack(anchor="w", pady=(5, 0))
        actions = frame(header)
        actions.grid(row=0, column=1, sticky="e")
        self.refresh_button = Button(actions, "更新行情", self.refresh_dashboard, width=110)
        self.refresh_button.pack(side="left", padx=(0, 10))
        self.run_button = Button(actions, "執行每日模型", self.run_model, primary=True, width=142)
        self.run_button.pack(side="left")

        status = frame(self.main)
        status.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        status.grid_columnconfigure(0, weight=1)
        times = frame(status)
        times.grid(row=0, column=0, sticky="w")
        Label(times, "模型", color="muted", size=12).pack(side="left", padx=(0, 8))
        Label(times, textvariable=self.vars["last_model_run"], size=13, number=True).pack(side="left", padx=(0, 16))
        self.daily_model_label = Label(times, textvariable=self.vars["daily_model"], size=13, color="accent")
        self.daily_model_label.pack(side="left")
        updates = frame(status)
        updates.grid(row=0, column=1, sticky="e")
        ctk.CTkSwitch(updates, text="自動更新", variable=self.auto_var, command=self.auto_changed,
                      font=font(13), width=100, switch_width=30, switch_height=17,
                      progress_color=UI_COLORS["accent"], button_color=UI_COLORS["text"],
                      fg_color=UI_COLORS["track"], text_color=UI_COLORS["muted"]).pack(side="left", padx=(0, 8))
        ctk.CTkOptionMenu(updates, values=["10 秒", "30 秒", "60 秒", "5 分鐘"],
                          variable=self.interval_var, command=lambda _: self.auto_changed(),
                          width=84, height=30, font=font(13), dropdown_font=font(13),
                          corner_radius=8, fg_color=UI_COLORS["surface_alt"],
                          button_color=UI_COLORS["surface_alt"], button_hover_color=UI_COLORS["track"],
                          dropdown_fg_color=UI_COLORS["surface_alt"], dropdown_hover_color=UI_COLORS["track"],
                          text_color=UI_COLORS["text"]).pack(side="left")

    def _notice(self):
        self.notice_frame = ctk.CTkFrame(self.main, corner_radius=10, fg_color="#32232B")
        self.notice_frame.grid_columnconfigure(0, weight=1)
        self.notice_text = Label(self.notice_frame, "", size=14, color="red", wraplength=750, justify="left")
        self.notice_text.grid(row=0, column=0, sticky="ew", padx=14, pady=10)
        Button(self.notice_frame, "關閉提示", self.dismiss_notice, width=80).grid(row=0, column=1, padx=10, pady=6)
        self._notice_after_id = None
        self._notice_message = None

    def notify(self, message, *, error=False):
        if message == self._notice_message:
            return
        self._notice_message = message
        if self._notice_after_id:
            self.after_cancel(self._notice_after_id)
            self._notice_after_id = None
        self.notice_frame.configure(fg_color="#32232B" if error else "#18302B")
        self.notice_text.configure(text=message, text_color=UI_COLORS["red" if error else "green"])
        self.notice_frame.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        if not error:
            self._notice_after_id = self.after(7000, self.dismiss_notice)

    def dismiss_notice(self):
        self.notice_frame.grid_remove()
        self._notice_message = None
        if self._notice_after_id:
            self.after_cancel(self._notice_after_id)
            self._notice_after_id = None

    def show_page(self, title):
        if title not in self.pages:
            return
        for page in self.pages.values():
            if isinstance(page, SmoothScrollPage):
                page.stop()
        self.pages[title].tkraise()
        self.page_title.configure(text=title)
        for name, button in self.nav_buttons.items():
            selected = name == title
            button.configure(fg_color="#302B1B" if selected else "transparent",
                             text_color=UI_COLORS["accent" if selected else "muted"])

    def _overview(self, parent):
        ticker = Card(parent)
        ticker.pack(fill="x", pady=(0, 16))
        for col, (asset, name) in enumerate((("btc", "Bitcoin"), ("eth", "Ethereum"))):
            box = frame(ticker.content)
            box.grid(row=0, column=col, sticky="ew", padx=(0, 22) if col == 0 else (22, 0))
            ticker.content.grid_columnconfigure(col, weight=1, uniform="ticker")
            top = frame(box)
            top.pack(fill="x")
            Label(top, asset.upper(), size=16, bold=True, color=asset, number=True).pack(side="left")
            Label(top, name, size=12, color="muted", number=True).pack(side="left", padx=10)
            Label(top, textvariable=self.vars[f"{asset}_time"], size=11, color="muted").pack(side="right")
            bottom = frame(box)
            bottom.pack(fill="x", pady=(7, 0))
            Label(bottom, textvariable=self.vars[f"{asset}_price"], size=28, bold=True, number=True).pack(side="left")
            change = Label(bottom, textvariable=self.vars[f"{asset}_change"], size=13, color="muted", number=True)
            change.pack(side="right")
            setattr(self, f"{asset}_change_label", change)

        self.main_grid = frame(parent)
        self.main_grid.pack(fill="x")
        self.main_left = frame(self.main_grid)
        self.main_right = frame(self.main_grid)
        self._wide = None
        self.main_grid.bind("<Configure>", self._responsive_layout, add="+")
        portfolios = frame(self.main_left)
        portfolios.pack(fill="x")
        self.pnl_labels = {}
        self.portfolio_cards = {}
        for col, (prefix, version, detail, color) in enumerate((
            ("h", "V3.10＋AI", "綜合版 · 紙上帳本", "green"),
            ("q", "V3.10", "純量化 · 凍結模型", "accent"),
        )):
            card = Card(portfolios)
            self.portfolio_cards[prefix] = card
            card.grid(row=0, column=col, sticky="nsew", padx=(0, 7) if col == 0 else (7, 0))
            portfolios.grid_columnconfigure(col, weight=1, uniform="portfolio")
            box = card.content
            head = frame(box)
            head.pack(fill="x")
            Label(head, version, size=20, bold=True, color=color, number=True).pack(side="left")
            Label(head, detail, size=11, color="muted").pack(side="right")
            Label(box, "紙上總資產 / USD", size=12, color="muted").pack(anchor="w", pady=(20, 3))
            Label(box, textvariable=self.vars[f"{prefix}_portfolio_total"], size=36, bold=True,
                  number=True).pack(anchor="w")
            state = ctk.CTkFrame(box, fg_color="#232C36", corner_radius=7)
            state.pack(anchor="w", pady=(12, 18))
            Label(state, textvariable=self.vars[f"{prefix}_state_label"], size=12).pack(padx=9, pady=5)
            bar = AllocationBar(box)
            bar.pack(fill="x", pady=(0, 12))
            self.allocation_canvases[prefix] = bar
            for asset, label in (("btc", "BTC"), ("eth", "ETH"), ("cash", "現金")):
                line = frame(box)
                line.pack(fill="x", pady=7)
                Label(line, f"●  {label}", size=14, color=asset).pack(side="left")
                Label(line, textvariable=self.vars[f"{prefix}_portfolio_{asset}"], size=14,
                      number=True).pack(side="right")
                if asset != "cash":
                    cost_line = frame(box)
                    cost_line.pack(fill="x", pady=(0, 4))
                    Label(cost_line, textvariable=self.vars[f"{prefix}_{asset}_average"], size=12,
                          color="muted", number=True).pack(side="left")
                    pnl = Label(cost_line, textvariable=self.vars[f"{prefix}_{asset}_pnl"], size=12,
                                color="muted", number=True)
                    pnl.pack(side="right")
                    self.pnl_labels[f"{prefix}_{asset}"] = pnl
            wrapping_label(box, textvariable=self.vars[f"{prefix}_cost_status"], size=11)
            wrapping_label(box, "浮動盈虧按目前估值；未含賣出費用，非帳戶總報酬。", size=11)
            ctk.CTkFrame(box, height=1, corner_radius=0, fg_color=UI_COLORS["border"]).pack(fill="x", pady=(15, 14))
            metrics = frame(box)
            metrics.pack(fill="x")
            for i, (label, suffix) in enumerate((("批准曝險" if prefix == "h" else "目標曝險", "target"), ("即時曝險", "actual"), ("量化階段", "stage"))):
                cell = frame(metrics)
                cell.grid(row=0, column=i, sticky="w")
                metrics.grid_columnconfigure(i, weight=1)
                Label(cell, label, size=11, color="muted").pack(anchor="w")
                Label(cell, textvariable=self.vars[f"{prefix}_{suffix}"], size=15,
                      number=True).pack(anchor="w", pady=(5, 0))
            meta = frame(box)
            meta.pack(fill="x", pady=(16, 0))
            wrapping_label(meta, textvariable=self.vars[f"{prefix}_portfolio_time"], size=11)
            wrapping_label(meta, textvariable=self.vars[f"{prefix}_decision_time"], size=11)
        note = frame(self.main_left)
        note.pack(fill="x", pady=(12, 16))
        wrapping_label(note, textvariable=self.vars["portfolio_status"], size=12)
        action = Card(self.main_left, "最近模型動作", subtitle="依最後一次成功執行的帳本紀錄")
        action.pack(fill="x", pady=(0, 10))
        wrapping_label(action.content, textvariable=self.action_var, color="text", size=14)

        progress = Card(self.main_right, "前瞻測試", subtitle="樣本外驗證進度")
        progress.pack(fill="x", pady=(0, 14))
        for label, name, maximum, color in (("樣本外天數", "oos", 180, "accent"),
                                             ("已判定 Stage3 候選", "candidate", 3, "blue")):
            line = frame(progress.content)
            line.pack(fill="x", pady=(0, 7))
            Label(line, label, size=12, color="muted").pack(side="left")
            text = Label(line, "等待資料", size=13, number=True)
            text.pack(side="right")
            bar = Progress(progress.content, maximum, color)
            bar.pack(fill="x", pady=(0, 16))
            setattr(self, f"{name}_text", text)
            setattr(self, f"{name}_bar", bar)
        warning_box = frame(progress.content)
        warning_box.pack(fill="x")
        self.eligibility_label = wrapping_label(warning_box, textvariable=self.vars["evaluation_eligibility"],
                                                 color="accent", size=13)
        risk = Card(self.main_right, "風險與連線")
        risk.pack(fill="x", pady=(0, 10))
        self._kv_rows(risk.content, [("崩盤訊號", "crash_label"), ("Stage3 候選", "stage3_label"),
                                    ("目前回撤", "drawdown"), ("AHR999", "ahr"), ("凍結檔案", "frozen_hash")])
        connection = frame(risk.content)
        connection.pack(fill="x", pady=(14, 0))
        self.market_status_label = wrapping_label(connection, textvariable=self.vars["market_status"], size=12)
        warnings = frame(risk.content)
        warnings.pack(fill="x", pady=(6, 0))
        wrapping_label(warnings, textvariable=self.vars["warning"], color="red", size=12)
        self._ai_summary_card()

    def _responsive_layout(self, event):
        logical_width = event.width / ctk.ScalingTracker.get_widget_scaling(self.main_grid)
        wide = logical_width >= 1160
        if wide == self._wide:
            return
        self._wide = wide
        self.main_left.grid(row=0, column=0, sticky="new", padx=(0, 16) if wide else 0)
        self.main_right.grid(row=0 if wide else 1, column=1 if wide else 0, sticky="new", pady=0 if wide else (6, 0))
        self.main_grid.grid_columnconfigure(0, weight=7)
        self.main_grid.grid_columnconfigure(1, weight=3 if wide else 0)

    def _reports(self):
        page = frame(self.host)
        self.pages["白話報告"] = page
        card = Card(page, "最新模型報告", subtitle="部位說明、判斷依據與風險提醒")
        card.pack(fill="both", expand=True)
        self.report_text = tk.Text(card.content, wrap="word", state="disabled", font=(UI_FONT, 11),
                                   background=UI_COLORS["surface"], foreground=UI_COLORS["text"],
                                   selectbackground="#36475B", insertbackground=UI_COLORS["text"],
                                   borderwidth=0, highlightthickness=0, padx=4, pady=8, spacing3=5)
        scrollbar = ctk.CTkScrollbar(card.content, command=self.report_text.yview, width=10,
                                    button_color=UI_COLORS["track"], button_hover_color=UI_COLORS["muted"])
        self.report_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(12, 0))
        self.report_text.pack(fill="both", expand=True)
        self.report_text.tag_configure("report_title", font=(UI_FONT, 16, "bold"), foreground=UI_COLORS["text"], spacing3=12)
        self.report_text.tag_configure("report_section", font=(UI_FONT, 12, "bold"), foreground=UI_COLORS["blue"], spacing1=10, spacing3=4)
        self.report_text.tag_configure("report_note", foreground=UI_COLORS["accent"], spacing1=6)

    def _execution_report(self):
        page = frame(self.host)
        self.pages["執行摘要"] = page
        card = Card(page, "模型做了什麼？", subtitle="成交時間 · 幣種 · 金額 · 原因｜紙上模擬，不會下單")
        card.pack(fill="both", expand=True)
        self.execution_text = tk.Text(
            card.content, wrap="word", state="disabled", font=(UI_FONT, 12),
            background=UI_COLORS["surface"], foreground=UI_COLORS["text"],
            selectbackground="#36475B", borderwidth=0, highlightthickness=0,
            padx=8, pady=10, spacing3=8,
        )
        scrollbar = ctk.CTkScrollbar(card.content, command=self.execution_text.yview,
                                    button_color=UI_COLORS["track"])
        self.execution_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.execution_text.pack(fill="both", expand=True)

    def _audit(self):
        page = SmoothScrollPage(self.host)
        self.pages["原始資料"] = page
        data = Card(page.content, "模型原始資料", subtitle="保留原始代碼與帳本時間，方便核對")
        data.pack(fill="x", pady=(0, 14))
        self._kv_rows(data.content, [("V3.10 狀態", "q_state"), ("V3.1 狀態", "b_state"),
                                    ("V3.10 曝險差距（百分點）", "q_gap"), ("兩模型曝險差（百分點）", "b_diff"),
                                    ("目前評估", "evaluation"), ("下一個風險觸發條件", "next_trigger"),
                                    ("帳本時間 UTC", "status_utc"), ("帳本時間 本機", "status_local")])
        action = Card(page.content, "最新動作代碼")
        action.pack(fill="x", pady=(0, 14))
        wrapping_label(action.content, textvariable=self.vars["action_raw"], color="text")
        recent = Card(page.content, "近期紀錄")
        recent.pack(fill="x", pady=(0, 10))
        self.recent_list = tk.Listbox(recent.content, height=8, borderwidth=0, highlightthickness=0,
                                     background=UI_COLORS["surface"], foreground=UI_COLORS["text"],
                                     font=(UI_FONT, 10), selectbackground="#36475B", activestyle="none")
        xbar = ctk.CTkScrollbar(recent.content, orientation="horizontal", command=self.recent_list.xview,
                                button_color=UI_COLORS["track"], button_hover_color=UI_COLORS["muted"], height=10)
        self.recent_list.configure(xscrollcommand=xbar.set)
        xbar.pack(side="bottom", fill="x")
        self.recent_list.pack(fill="x")

    def _kv_rows(self, parent, rows):
        group = frame(parent)
        group.pack(fill="x")
        group.grid_columnconfigure(1, weight=1)
        for row, (label, key) in enumerate(rows):
            Label(group, label, size=13, color="muted").grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=6)
            Label(group, textvariable=self.vars[key], size=13, wraplength=400,
                  justify="right", number=True).grid(row=row, column=1, sticky="ne", pady=6)

    def show_tools(self):
        menu = tk.Menu(self, tearoff=False, background=UI_COLORS["surface_alt"], foreground=UI_COLORS["text"],
                       activebackground=UI_COLORS["track"], activeforeground=UI_COLORS["text"], font=(UI_FONT, 11))
        for label, path in (("開啟封存", self.storage.archive_dir), ("開啟日誌", self.storage.logs_dir),
                            ("開啟設定", self.config_path), ("開啟資料夾", self.storage.data_dir)):
            menu.add_command(label=label, command=lambda p=path: self.open_path(p))
        menu.add_separator()
        menu.add_command(label='ChatGPT 與 AI 設定…',command=self.show_ai_settings)
        menu.add_separator()
        menu.add_command(label="強制執行模型…", command=self.force_run)
        menu.add_separator()
        menu.add_command(label="離開", command=self.close)
        try:
            menu.tk_popup(self.tools_button.winfo_rootx() + self.tools_button.winfo_width(),
                          self.tools_button.winfo_rooty())
        finally:
            menu.grab_release()

    def show_help(self):
        window = ctk.CTkToplevel(self)
        window.title("使用說明")
        window.geometry("620x430")
        window.configure(fg_color=UI_COLORS["background"])
        card = Card(window, "如何使用", subtitle="監控與執行分開，保留紙上交易邊界")
        card.pack(fill="both", expand=True, padx=18, pady=18)
        wrapping_label(card.content, text=(
            "1. 更新行情 / F5：只更新價格與畫面，不會執行交易。\n\n"
            "2. 執行每日模型：按一次即可，執行期間可繼續瀏覽。\n\n"
            "3. 目標曝險是模型目標；帳本曝險是最後執行的紀錄。"
            "配置金額依目前可用市價估算，因此兩者可能不同。\n\n"
            "4. 頁面可用滑鼠滾輪捲動；Ctrl+1 / 2 / 3 切換分頁。\n\n"
            "這不是交易所帳戶，不會替你下真實訂單。"
        ), color="text", size=14)
        Button(card.content, "知道了", window.destroy).pack(anchor="e", pady=(16, 0))
        window.after(100, window.lift)
