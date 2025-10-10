import argparse
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from matplotlib.widgets import Slider
from matplotlib.axes import Axes
from matplotlib.lines import Line2D

from loaders.measurement import Measurement

# Keep references to widgets/figures to avoid garbage collection breaking interactivity
_WIDGETS_KEEPALIVE: list = []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Path to the results")
    parser.add_argument("--resample-ms", type=int, default=200, help="Interval for resampling rate graphs in ms")
    parser.add_argument("--dishy-trail", type=int, default=15, help="Trail length in seconds for Dishy position heatmap")
    parser.add_argument("--plot-fps", type=bool, default=False, help="Add a plot for FPS if available")
    args = parser.parse_args()

    ms = Measurement(args.path)
    ms.load_files()

    send_br = ms.get_send_bitrate_kbps(args.resample_ms)
    recv_br = ms.get_recv_bitrate_kbps(args.resample_ms)
    loss_rate = ms.get_loss_rate()
    rtt = ms.get_rtt_ms()
    jitter = ms.get_jitter_ms()
    reconfig_times = ms.get_reconfiguration_times()
    cong_br = ms.get_congestion_bitrates()
    delay_estimate = ms.get_delay_estimate_ms()
    feedback_interval = ms.get_feedback_interval_ms()
    cong_states = ms.get_congestion_states()
    icmp_pings = ms.get_icmp_pings()
    send_fps = ms.get_send_fps() if args.plot_fps else None
    recv_fps = ms.get_recv_fps() if args.plot_fps else None
    probe_timestamps = ms.get_probe_timestamps()
    guard_trigger_timestamps = ms.get_guard_trigger_timestamps()
    num_plots = 3 \
        + (1 if jitter is not None else 0) \
        + (1 if cong_br is not None else 0) \
        + (1 if delay_estimate is not None else 0) \
        + (1 if feedback_interval is not None else 0) \
        + (1 if (cong_states is not None and not cong_states.empty) else 0) \
        + (1 if icmp_pings is not None else 0) \
        + (1 if (args.plot_fps and (send_fps is not None or recv_fps is not None)) else 0)
    heights = {2: 8, 3: 10, 4: 12, 5: 14, 6: 16, 7: 18, 8: 20, 9: 22}
    fig, axes = plt.subplots(num_plots, 1, sharex=True, figsize=(10, heights.get(num_plots, 12)))
    axes_list: list[Axes] = np.atleast_1d(axes).ravel().tolist()  # type: ignore[assignment]
    ax1: Axes = axes_list[0]  # Bitrate
    ax_loss: Axes = axes_list[1]  # Loss
    ax2: Axes = axes_list[2]  # RTT
    idx = 3
    ax3: Axes | None = None
    ax_cong: Axes | None = None
    ax_delay: Axes | None = None
    ax_feedback_interval: Axes | None = None
    ax_states: Axes | None = None
    ax_fps: Axes | None = None
    ax_icmp_pings: Axes | None = None
    if jitter is not None and idx < len(axes_list):
        ax3 = axes_list[idx]
        idx += 1
    if cong_br is not None and idx < len(axes_list):
        ax_cong = axes_list[idx]
        idx += 1
    if delay_estimate is not None and idx < len(axes_list):
        ax_delay = axes_list[idx]
        idx += 1
    if feedback_interval is not None and idx < len(axes_list):
        ax_feedback_interval = axes_list[idx]
        idx += 1
    if (args.plot_fps and (send_fps is not None or recv_fps is not None)) and idx < len(axes_list):
        ax_fps = axes_list[idx]
        idx += 1
    if (cong_states is not None and not cong_states.empty) and idx < len(axes_list):
        ax_states = axes_list[idx]
        idx += 1
    if icmp_pings is not None and idx < len(axes_list):
        ax_icmp_pings = axes_list[idx]

    # Plot bitrates
    ax1.plot(send_br.index, send_br.values, label='Send Bitrate (kbps)')
    ax1.plot(recv_br.index, recv_br.values, label='Recv Bitrate (kbps)')
    ax1.set_ylabel('Bitrate (kbps)')
    ax1.set_title('Bitrate Over Time')
    ax1.grid(True)
    ax1.legend()

    # Plot Loss Rate (always second)
    if loss_rate is not None:
        ax_loss.plot(loss_rate.index, loss_rate.values * 100, label='Loss Rate (%)', color='tab:gray')
        ax_loss.set_ylabel('Loss Rate (%)')
        ax_loss.set_title('Loss Rate Over Time')
        ax_loss.grid(True)
        ax_loss.legend()

    # Plot RTT (if available)
    if rtt is not None:
        ax2.plot(rtt.index, rtt.values, label='RTT (ms)', color='tab:red')
        ax2.set_xlabel('Time')
        ax2.set_ylabel('RTT (ms)')
        ax2.set_title('RTT Over Time')
        ax2.grid(True)
        ax2.legend()

    # Plot Jitter (if available)
    if jitter is not None and ax3 is not None:
        ax3.plot(jitter.index, jitter.values, label='Jitter (ms)', color='tab:purple')

    # Plot congestion bitrates (if available)
    if cong_br is not None and ax_cong is not None and not cong_br.empty:
        palette = sns.color_palette(n_colors=len(cong_br.columns))
        for i, col in enumerate(cong_br.columns):
            ax_cong.plot(cong_br.index, cong_br[col].values, label=col, color=palette[i % len(palette)])
        ax_cong.set_xlabel('Time')
        ax_cong.set_ylabel('Bitrate (kbps)')
        ax_cong.set_title('Congestion Bitrates Over Time')
        ax_cong.grid(True)
        ax_cong.legend()

    # Plot delay estimate (if available)
    if delay_estimate is not None and ax_delay is not None:
        ax_delay.plot(delay_estimate.index, delay_estimate.values, label='Delay Estimate (ms)', color='tab:blue')
        ax_delay.set_xlabel('Time')
        ax_delay.set_ylabel('Delay Estimate (ms)')
        ax_delay.set_title('Delay Estimate Over Time')
        ax_delay.grid(True)
        ax_delay.legend()

    if feedback_interval is not None and ax_feedback_interval is not None:
        ax_feedback_interval.plot(feedback_interval.index, feedback_interval.values, label='Feedback interval (ms)', color='tab:blue')
        ax_feedback_interval.set_xlabel('Time')
        ax_feedback_interval.set_ylabel('Feedback interval (ms)')
        ax_feedback_interval.set_title('Feedback interval Over Time')
        ax_feedback_interval.grid(True)
        ax_feedback_interval.legend()

    if (args.plot_fps and ax_fps is not None) and (send_fps is not None or recv_fps is not None):
        if send_fps is not None:
            ax_fps.plot(send_fps.index, send_fps.values, label='Send FPS')
        if recv_fps is not None:
            ax_fps.plot(recv_fps.index, recv_fps.values, label='Recv FPS')
        ax_fps.set_xlabel('Time')
        ax_fps.set_ylabel('FPS')
        ax_fps.set_title('FPS Over Time')
        ax_fps.grid(True)
        ax_fps.legend()

    # Plot congestion states (if available) as colored timelines per column
    if cong_states is not None and ax_states is not None and not cong_states.empty:
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
    role_colors = {"sender": "tab:orange", "receiver": "tab:green"}
    shown_roles = set()
    all_axes: list[Axes] = [ax1, ax_loss, ax2]
    if ax3 is not None:
        all_axes.append(ax3)
    if ax_cong is not None:
        all_axes.append(ax_cong)
    if ax_delay is not None:
        all_axes.append(ax_delay)
    if ax_feedback_interval is not None:
        all_axes.append(ax_feedback_interval)
    if ax_fps is not None:
        all_axes.append(ax_fps)
    if ax_states is not None:
        all_axes.append(ax_states)
    for role, ts in reconfig_times:
        label = f"Reconfig ({role})" if role not in shown_roles else None
        for i, ax in enumerate(all_axes):
            ax.axvline(ts, color=role_colors.get(role, "k"), linestyle="-", linewidth=2.0, label=label if i == 0 else None)
        shown_roles.add(role)

    if probe_timestamps is not None:
        for i, (ax, ts) in enumerate([(ax, ts) for ax in all_axes for ts in probe_timestamps]):
            label = "Probe" if i == 0 else None
            ax.axvline(ts, color="purple", linestyle=(0, (5, 2)), linewidth=1.5, label=label)

    if guard_trigger_timestamps is not None:
        for i, (ax, ts) in enumerate([(ax, ts) for ax in all_axes for ts in guard_trigger_timestamps]):
            label = "Guard Trigger" if i == 0 else None
            ax.axvline(ts, color="green", linestyle=(0, (1, 1)), linewidth=1.0, label=label)

    if icmp_pings is not None:
        ax_icmp_pings.plot(icmp_pings.index, icmp_pings.values, label='ICMP RTT', color='tab:gray')
        ax_icmp_pings.set_ylabel('RTT (ms)')
        ax_icmp_pings.set_title('ICMP RTT')
        ax_icmp_pings.grid(True)
        ax_icmp_pings.legend()

    ax1.set_ylabel('Bitrate (kbps)')
    ax1.set_title('Bitrate Over Time')
    ax1.grid(True)
    ax1.legend()

    ax2.set_xlabel('Time')
    ax2.set_ylabel('RTT (ms)')
    ax2.set_title('RTT Over Time')
    ax2.grid(True)
    if rtt is not None:
        ax2.legend()

    if jitter is not None and ax3 is not None:
        ax3.set_xlabel('Time')
        ax3.set_ylabel('Jitter (ms)')
        ax3.set_title('Jitter Over Time')
        ax3.grid(True)
        ax3.legend()

    # Dishy 2D heatmap with slider (if available)
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

    fig.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()