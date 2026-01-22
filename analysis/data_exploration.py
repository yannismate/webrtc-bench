import argparse
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from matplotlib.widgets import Slider
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
import matplotlib.dates as mdates

from loaders.measurement import Measurement

# Keep references to widgets/figures to avoid garbage collection breaking interactivity
_WIDGETS_KEEPALIVE: list = []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Path to the results")
    parser.add_argument("--resample-ms", type=int, default=200, help="Interval for resampling rate graphs in ms")
    parser.add_argument("--dishy-trail", type=int, default=15, help="Trail length in seconds for Dishy position heatmap")
    parser.add_argument(
        "--graphs",
        type=str,
        help=(
            "Comma-separated list of graphs to plot. Options: bitrate, loss, rtt, irtt, jitter, "
            "congestion, delay, feedback, fps, states, icmp. Default shows all available."
        ),
    )
    args = parser.parse_args()

    graph_names = {
        "bitrate",
        "loss",
        "rtt",       # WebRTC/parquet RTT
        "irtt",      # IRTT RTT
        "jitter",
        "congestion",
        "delay",
        "feedback",
        "fps",
        "states",
        "icmp",
    }
    alias_map = {
        "rtt_parquet": ["rtt"],
        "rtt_irtt": ["irtt"],
        "rttall": ["rtt", "irtt"],
    }
    selected_graphs: set[str] | None = None
    if args.graphs:
        parsed = [g.strip().lower() for g in args.graphs.split(",") if g.strip()]
        if not parsed:
            parser.error("--graphs provided but no graph names found")
        if "all" in parsed:
            selected_graphs = None
        else:
            expanded: list[str] = []
            for g in parsed:
                expanded.extend(alias_map.get(g, [g]))
            invalid = [g for g in expanded if g not in graph_names]
            if invalid:
                parser.error(f"Invalid graph names: {', '.join(invalid)}")
            selected_graphs = set(expanded)

    ms = Measurement(args.path)
    ms.load_files()

    send_br = ms.get_send_bitrate_kbps(args.resample_ms)
    recv_br = ms.get_recv_bitrate_kbps(args.resample_ms)
    loss_rate = ms.get_loss_rate()
    rtt_webrtc = ms.get_parquet_rtt_ms()
    rtt_irtt = ms.get_irtt_rtt_ms()
    jitter = ms.get_jitter_ms()
    reconfig_times = ms.get_reconfiguration_times()
    cong_br = ms.get_congestion_bitrates()
    delay_estimate = ms.get_delay_estimate_ms()
    feedback_interval = ms.get_feedback_interval_ms()
    cong_states = ms.get_congestion_states()
    icmp_pings = ms.get_icmp_pings()
    # FPS is now always loaded if available
    send_fps = ms.get_send_fps()
    recv_fps = ms.get_recv_fps()
    freeze_times = ms.get_freeze_times()
    probe_timestamps = ms.get_probe_timestamps()
    guard_trigger_timestamps = ms.get_guard_trigger_timestamps()

    availability = {
        "bitrate": (send_br is not None and not send_br.empty) or (recv_br is not None and not recv_br.empty),
        "loss": loss_rate is not None and not loss_rate.empty,
        "rtt": rtt_webrtc is not None,
        "irtt": rtt_irtt is not None,
        "jitter": jitter is not None,
        "congestion": cong_br is not None and not cong_br.empty,
        "delay": delay_estimate is not None,
        "feedback": feedback_interval is not None,
        "fps": (send_fps is not None or recv_fps is not None),
        "states": cong_states is not None and not cong_states.empty,
        "icmp": icmp_pings is not None,
    }

    def should_show(name: str) -> bool:
        return availability[name] and (selected_graphs is None or name in selected_graphs)

    show_bitrate = should_show("bitrate")
    show_loss = should_show("loss")
    show_rtt_webrtc = should_show("rtt")
    show_rtt_irtt = should_show("irtt")
    show_jitter = should_show("jitter")
    show_cong = should_show("congestion")
    show_delay = should_show("delay")
    show_feedback = should_show("feedback")
    show_fps = should_show("fps")
    show_states = should_show("states")
    show_icmp = should_show("icmp")

    # Order plots with IRTT near ICMP at the bottom
    plot_flags_ordered = [
        ("bitrate", show_bitrate),
        ("loss", show_loss),
        ("rtt_webrtc", show_rtt_webrtc),
        ("jitter", show_jitter),
        ("congestion", show_cong),
        ("delay", show_delay),
        ("feedback", show_feedback),
        ("fps", show_fps),
        ("states", show_states),
        ("icmp", show_icmp),
        ("irtt", show_rtt_irtt),
    ]
    num_plots = sum(flag for _, flag in plot_flags_ordered)
    heights = {2: 8, 3: 10, 4: 12, 5: 14, 6: 16, 7: 18, 8: 20, 9: 22, 10: 24, 11: 26}
    fig = None
    axes_list: list[Axes] = []
    if num_plots > 0:
        fig, axes = plt.subplots(num_plots, 1, sharex=True, figsize=(10, heights.get(num_plots, 12)))
        axes_list = np.atleast_1d(axes).ravel().tolist()  # type: ignore[assignment]

    ax1: Axes | None = None
    ax_loss: Axes | None = None
    ax_rtt_webrtc: Axes | None = None
    ax_rtt_irtt: Axes | None = None
    ax_jitter: Axes | None = None
    ax_cong: Axes | None = None
    ax_delay: Axes | None = None
    ax_feedback_interval: Axes | None = None
    ax_states: Axes | None = None
    ax_fps: Axes | None = None
    ax_icmp_pings: Axes | None = None

    idx = 0
    for name, flag in plot_flags_ordered:
        if not flag:
            continue
        ax = axes_list[idx]
        idx += 1
        if name == "bitrate":
            ax1 = ax
        elif name == "loss":
            ax_loss = ax
        elif name == "rtt_webrtc":
            ax_rtt_webrtc = ax
        elif name == "jitter":
            ax_jitter = ax
        elif name == "congestion":
            ax_cong = ax
        elif name == "delay":
            ax_delay = ax
        elif name == "feedback":
            ax_feedback_interval = ax
        elif name == "fps":
            ax_fps = ax
        elif name == "states":
            ax_states = ax
        elif name == "icmp":
            ax_icmp_pings = ax
        elif name == "irtt":
            ax_rtt_irtt = ax

    # Plot RTT (WebRTC/parquet if available)
    if ax_rtt_webrtc is not None and rtt_webrtc is not None:
        ax_rtt_webrtc.plot(rtt_webrtc.index, rtt_webrtc.values, label='RTT (WebRTC, ms)', color='tab:red')
        ax_rtt_webrtc.set_xlabel('Time')
        ax_rtt_webrtc.set_ylabel('RTT (ms)')
        ax_rtt_webrtc.set_title('RTT (WebRTC) Over Time')
        ax_rtt_webrtc.grid(True)
        ax_rtt_webrtc.legend()

    # Plot RTT (IRTT)
    if ax_rtt_irtt is not None and rtt_irtt is not None:
        ax_rtt_irtt.plot(rtt_irtt.index, rtt_irtt.values, label='RTT (IRTT, ms)', color='tab:orange')
        ax_rtt_irtt.set_xlabel('Time')
        ax_rtt_irtt.set_ylabel('RTT (ms)')
        ax_rtt_irtt.set_title('RTT (IRTT) Over Time')
        ax_rtt_irtt.grid(True)
        ax_rtt_irtt.legend()

    # Plot loss rate
    if ax_loss is not None and loss_rate is not None and not loss_rate.empty:
        loss_series = loss_rate
        ylabel = "Loss rate"
        cleaned = loss_series.dropna()
        if not cleaned.empty and cleaned.le(1.0).all():
            loss_series = loss_series * 100.0
            ylabel = "Loss (%)"
        ax_loss.plot(loss_series.index, loss_series.values, label='Loss', color='tab:blue')
        ax_loss.set_xlabel('Time')
        ax_loss.set_ylabel(ylabel)
        ax_loss.set_title('Loss Over Time')
        ax_loss.grid(True)
        ax_loss.legend()

    # Plot Jitter (if available)
    if ax_jitter is not None and jitter is not None:
        ax_jitter.plot(jitter.index, jitter.values, label='Jitter (ms)', color='tab:purple')

    # Plot congestion bitrates (if available)
    if ax_cong is not None and cong_br is not None and not cong_br.empty:
        palette = sns.color_palette(n_colors=len(cong_br.columns))
        for i, col in enumerate(cong_br.columns):
            ax_cong.plot(cong_br.index, cong_br[col].values, label=col, color=palette[i % len(palette)])
        ax_cong.set_xlabel('Time')
        ax_cong.set_ylabel('Bitrate (kbps)')
        ax_cong.set_title('Congestion Bitrates Over Time')
        ax_cong.grid(True)
        ax_cong.legend()

    # Plot delay estimate (if available)
    if ax_delay is not None and delay_estimate is not None:
        ax_delay.plot(delay_estimate.index, delay_estimate.values, label='Delay Estimate (ms)', color='tab:blue')
        ax_delay.set_xlabel('Time')
        ax_delay.set_ylabel('Delay Estimate (ms)')
        ax_delay.set_title('Delay Estimate Over Time')
        ax_delay.grid(True)
        ax_delay.legend()

    # Plot feedback interval
    if ax_feedback_interval is not None and feedback_interval is not None:
        ax_feedback_interval.plot(feedback_interval.index, feedback_interval.values, label='Feedback interval (ms)', color='tab:blue')
        ax_feedback_interval.set_xlabel('Time')
        ax_feedback_interval.set_ylabel('Feedback interval (ms)')
        ax_feedback_interval.set_title('Feedback interval Over Time')
        ax_feedback_interval.grid(True)
        ax_feedback_interval.legend()

    if ax_fps is not None and (send_fps is not None or recv_fps is not None):
        if send_fps is not None:
            ax_fps.plot(send_fps.index, send_fps.values, label='Send FPS')
        if recv_fps is not None:
            ax_fps.plot(recv_fps.index, recv_fps.values, label='Recv FPS')
        ax_fps.set_xlabel('Time')
        ax_fps.set_ylabel('FPS')
        ax_fps.set_title('FPS Over Time')
        ax_fps.grid(True)
        ax_fps.legend()
        if freeze_times is not None and not freeze_times.empty:
            for i, ts in enumerate(freeze_times.index):
                label = "Freeze" if i == 0 else None
                ax_fps.axvline(ts, color='red', linestyle='--', linewidth=1.0, alpha=0.7, label=label)
            ax_fps.legend()

    # Plot congestion states (if available) as colored timelines per column
    if ax_states is not None and cong_states is not None and not cong_states.empty:
        cols = list(cong_states.columns)
        y_positions = np.arange(len(cols))
        # Determine global time range across measurement to close last segment
        global_start, global_end = ms.get_timestamp_range()
        # Build a global color map across all unique states (excluding NaN)
        unique_states_global = []
        for col in cols:
            unique_states_global.extend(cong_states[col].dropna().astype(str).unique().tolist())
        # Preserve order of first appearance
        seen = set()
        unique_states_global = [x for x in unique_states_global if not (x in seen or seen.add(x))]
        colors = sns.color_palette("tab20", n_colors=len(unique_states_global) if unique_states_global else 1)
        color_map = {st: colors[j % len(colors)] for j, st in enumerate(unique_states_global)}
        for i, col in enumerate(cols):
            s = cong_states[col].dropna()
            if s.empty:
                continue
            # Use string labels for stable color mapping and comparisons
            s_str = s.astype(str)
            # Build contiguous segments of identical state
            prev_state = s_str.iloc[0]
            seg_start = s_str.index[0]
            for t, st in zip(s_str.index[1:], s_str.iloc[1:]):
                if st != prev_state:
                    # Draw segment from seg_start to t
                    ax_states.plot([seg_start, t], [i, i], color=color_map.get(prev_state, 'k'), linewidth=6, solid_capstyle='butt')
                    seg_start = t
                    prev_state = st
            # Close final segment to global_end
            t_end = max(seg_start, global_end)
            ax_states.plot([seg_start, t_end], [i, i], color=color_map.get(prev_state, 'k'), linewidth=6, solid_capstyle='butt')
        ax_states.set_yticks(y_positions)
        ax_states.set_yticklabels(cols)
        ax_states.set_ylim(-1, len(cols))
        ax_states.set_xlabel('Time')
        ax_states.set_ylabel('States')
        ax_states.set_title('Congestion States Over Time')
        ax_states.grid(True, axis='x')
        # Add legend mapping colors to state labels (if any)
        if unique_states_global:
            handles = [Line2D([0], [0], color=color_map[st], lw=6) for st in unique_states_global]
            ax_states.legend(handles, unique_states_global, title='States', loc='upper right', fontsize='small')

    # Plot reconfigurations on all axes
    role_colors = {"sender": "#f11c64", "receiver": "tab:green"}
    shown_roles = set()
    all_axes: list[Axes] = []
    for ax in [ax1, ax_loss, ax_rtt_webrtc, ax_jitter, ax_cong, ax_delay, ax_feedback_interval, ax_fps, ax_states, ax_icmp_pings, ax_rtt_irtt]:
        if ax is not None:
            all_axes.append(ax)
    for role, ts in reconfig_times:
        label = f"Handover ({role})" if role not in shown_roles else None
        for i, ax in enumerate(all_axes):
            ax.axvline(ts, color=role_colors.get(role, "k"), linestyle="-", linewidth=2.0, alpha=0.3, label=label if i == 0 else None)
        shown_roles.add(role)

    if probe_timestamps is not None:
        for i, (ax, ts) in enumerate([(ax, ts) for ax in all_axes for ts in probe_timestamps]):
            label = "Probe" if i == 0 else None
            ax.axvline(ts, color="purple", linestyle=(0, (5, 2)), linewidth=1.5, label=label)

    if guard_trigger_timestamps is not None:
        for i, (ax, ts) in enumerate([(ax, ts) for ax in all_axes for ts in guard_trigger_timestamps]):
            label = "Guard Trigger" if i == 0 else None
            ax.axvline(ts, color="green", linestyle=(0, (1, 1)), linewidth=1.0, label=label)

    # Plot ICMP RTT
    if ax_icmp_pings is not None and icmp_pings is not None:
        ax_icmp_pings.plot(icmp_pings.index, icmp_pings.values, label='ICMP RTT', color='tab:gray')
        ax_icmp_pings.set_ylabel('RTT (ms)')
        ax_icmp_pings.set_title('ICMP RTT')
        ax_icmp_pings.grid(True)
        ax_icmp_pings.legend()

    # Plot Bitrate
    if ax1 is not None:
        if send_br is not None and not send_br.empty:
            ax1.plot(send_br.index, send_br.values, label='Send Bitrate (kbps)')
        if recv_br is not None and not recv_br.empty:
            ax1.plot(recv_br.index, recv_br.values, label='Recv Bitrate (kbps)')
        ax1.set_ylabel('Bitrate (kbps)')
        ax1.set_title('Bitrate Over Time')
        ax1.grid(True)
        if ax1.lines:
            ax1.legend()

    if ax_rtt_webrtc is not None:
        ax_rtt_webrtc.set_xlabel('Time')
        ax_rtt_webrtc.set_ylabel('RTT (ms)')
        ax_rtt_webrtc.set_title('RTT (WebRTC) Over Time')
        ax_rtt_webrtc.grid(True)

    if ax_rtt_irtt is not None:
        ax_rtt_irtt.set_xlabel('Time')
        ax_rtt_irtt.set_ylabel('RTT (ms)')
        ax_rtt_irtt.set_title('RTT (IRTT) Over Time')
        ax_rtt_irtt.grid(True)

    if ax_jitter is not None and jitter is not None:
        ax_jitter.set_xlabel('Time')
        ax_jitter.set_ylabel('Jitter (ms)')
        ax_jitter.set_title('Jitter Over Time')
        ax_jitter.grid(True)
        ax_jitter.legend()

    def set_custom_grid(ax):
        locator = mdates.SecondLocator(bysecond=[12, 27, 42, 57])
        ax.xaxis.set_major_locator(locator)
        ax.grid(True, which='major', axis='x')

    for ax in [
        ax1,
        ax_loss,
        ax_rtt_webrtc,
        ax_rtt_irtt,
        ax_jitter,
        ax_cong,
        ax_delay,
        ax_feedback_interval,
        ax_fps,
        ax_states,
        ax_icmp_pings,
    ]:
        if ax is not None:
            set_custom_grid(ax)

    def create_dishy_imshow(dishy_data, title_prefix: str):
        if dishy_data is None:
            return
        positions = getattr(dishy_data, 'positions', None)
        if positions is None or getattr(positions, 'empty', True):
            return
        num_rows = getattr(dishy_data, 'num_rows', None)
        num_cols = getattr(dishy_data, 'num_columns', None)
        if not isinstance(num_rows, int) or not isinstance(num_cols, int):
            return
        trail = max(1, int(args.dishy_trail))

        # Prepare time axis in seconds since first observation
        times = positions['time']
        # Ensure sorted by time (loader already does this, but keep safe)
        positions_sorted = positions.sort_values('time').reset_index(drop=True)
        times = positions_sorted['time']
        rows_arr = positions_sorted['row'].to_numpy(dtype=int)
        cols_arr = positions_sorted['col'].to_numpy(dtype=int)
        t0 = times.iloc[0]
        times_sec = (times - t0).dt.total_seconds().to_numpy()
        t_max = float(times_sec[-1]) if len(times_sec) > 0 else 0.0
        # Slider requires valmin < valmax; if only one point, make a tiny range
        if t_max <= 0.0:
            t_max = 1.0

        # Separate figure for the heatmap and a slider below
        fig_hm, ax_hm = plt.subplots(figsize=(6, 6))
        slider_ax = fig_hm.add_axes((0.15, 0.05, 0.7, 0.03))

        def compute_heat(t_s: float) -> np.ndarray:
            heat = np.zeros((num_rows, num_cols), dtype=float)
            start_t = max(0.0, t_s - float(trail))
            # Mask rows within trailing window [start_t, t_s]
            mask = (times_sec >= start_t) & (times_sec <= t_s)
            idxs = np.nonzero(mask)[0]
            if idxs.size == 0:
                return heat
            # Linear weight from oldest (0) to newest (1) within the window
            denom = max(t_s - start_t, 1e-9)
            for k in idxs:
                ri = rows_arr[k]
                ci = cols_arr[k]
                if 0 <= ri < num_rows and 0 <= ci < num_cols:
                    w = (times_sec[k] - start_t) / denom
                    if w > heat[ri, ci]:
                        heat[ri, ci] = w
            return heat

        init_t = float(times_sec[-1]) if len(times_sec) > 0 else 0.0
        img = ax_hm.imshow(
            compute_heat(init_t),
            cmap='magma', vmin=0.0, vmax=1.0, interpolation='nearest', origin='upper'
        )
        ax_hm.set_title(f"{title_prefix} Dishy positions (trail={trail}s)")
        ax_hm.set_xlabel('Column')
        ax_hm.set_ylabel('Row')
        ax_hm.set_xlim(-0.5, num_cols - 0.5)
        ax_hm.set_ylim(num_rows - 0.5, -0.5)
        ax_hm.grid(False)
        cbar = fig_hm.colorbar(img, ax=ax_hm, fraction=0.046, pad=0.04)
        cbar.set_label('Recency (1 = current)')

        slider = Slider(ax=slider_ax, label='Time (s)', valmin=0.0, valmax=t_max, valinit=init_t)

        def on_change(_):
            t_s = float(slider.val)
            img.set_data(compute_heat(t_s))
            fig_hm.canvas.draw_idle()

        slider.on_changed(on_change)

        # Keep strong references around to avoid GC breaking callbacks
        _WIDGETS_KEEPALIVE.extend([fig_hm, ax_hm, img, slider])

    # Prefer sender; also show receiver if available
    if getattr(ms, 'data_dishy_sender', None) is not None:
        create_dishy_imshow(ms.data_dishy_sender, title_prefix='Sender')
    if getattr(ms, 'data_dishy_receiver', None) is not None:
        create_dishy_imshow(ms.data_dishy_receiver, title_prefix='Receiver')

    if fig is not None:
        fig.tight_layout()
    if num_plots > 0 or _WIDGETS_KEEPALIVE:
        plt.show()

if __name__ == "__main__":
    main()
