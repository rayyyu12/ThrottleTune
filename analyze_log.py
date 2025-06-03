import csv
import argparse
from collections import Counter, defaultdict

# --- Constants (can be adjusted if your main script's constants change) ---
DEFAULT_THROTTLE_DEADZONE_LOW = 0.05
DEFAULT_LIGHT_BLIP_GESTURE_COOLDOWN = 0.25
SUSPICIOUSLY_HIGH_IDLE_THROTTLE = 0.10 
RAPID_BLIP_THRESHOLD_SECONDS = 0.15 

def parse_value(value_str):
    """Attempt to convert string value to bool, int, float, or keep as string."""
    if value_str is None: return None
    val_lower = value_str.lower()
    if val_lower == 'true': return True
    if val_lower == 'false': return False
    try: return int(value_str)
    except ValueError:
        try: return float(value_str)
        except ValueError: return value_str

def load_and_parse_csv(filepath):
    data = []
    try:
        with open(filepath, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            if not reader.fieldnames:
                print(f"Error: CSV file '{filepath}' is empty or has no header row.")
                return None
            for i, row_dict in enumerate(reader):
                parsed_row = {}
                for key, value_str in row_dict.items():
                    parsed_row[key] = parse_value(value_str)
                
                parsed_row.setdefault('timestamp_unix', float(i))
                parsed_row.setdefault('dt', 1/60.0) 
                parsed_row.setdefault('raw_throttle_input_pct', 0.0) 
                parsed_row.setdefault('smoothed_throttle_pct', 0.0)
                parsed_row.setdefault('state', 'UNKNOWN')
                parsed_row.setdefault('active_blip_count', 0)
                parsed_row.setdefault('sim_last_blip_time', 0.0)
                parsed_row.setdefault('sim_in_pot_gesture', False)
                parsed_row.setdefault('sim_peak_thr_gesture', 0.0)

                data.append(parsed_row)
    except FileNotFoundError:
        print(f"Error: Log file not found at '{filepath}'")
        return None
    except Exception as e:
        print(f"Error reading or parsing CSV file '{filepath}': {e}")
        import traceback
        traceback.print_exc()
        return None
    if not data:
        print(f"Log file '{filepath}' is empty or could not be parsed into data.")
        return None
    return data

def print_log_excerpt(log_data, index, window=2, label=""):
    print(f"\n--- Log Excerpt: {label} (around index {index}, timestamp {log_data[index].get('timestamp_unix', 'N/A'):.2f}) ---")
    start = max(0, index - window)
    end = min(len(log_data), index + window + 1)
    if not log_data: return

    relevant_headers = [
        'datetime_iso', 'timestamp_unix', 'state', 
        'raw_throttle_input_pct', 'smoothed_throttle_pct', 
        'sim_in_pot_gesture', 'sim_peak_thr_gesture',
        'active_blip_count', 'sim_last_blip_time', 'sfx_chan_sound'
    ]
    actual_headers = [h for h in relevant_headers if h in log_data[0]] 
    if not actual_headers: 
        actual_headers = list(log_data[0].keys())[:8] 

    print(" | ".join(actual_headers))

    for i in range(start, end):
        row_values = []
        for h in actual_headers:
            val = log_data[i].get(h, 'N/A')
            if isinstance(val, float):
                val = f"{val:.3f}"
            row_values.append(str(val))
        marker = " *** " if i == index else "     "
        print(marker + " | ".join(row_values))
    print("--- End Excerpt ---")


def analyze_general_stats(log_data):
    print("\n--- General Statistics ---")
    if not log_data:
        print("No data to analyze.")
        return

    total_entries = len(log_data)
    print(f"Total log entries: {total_entries}")

    first_ts = log_data[0].get('timestamp_unix', 0.0)
    last_ts = log_data[-1].get('timestamp_unix', 0.0)
    total_duration = last_ts - first_ts if total_entries > 1 else 0.0
    print(f"Total log duration: {total_duration:.2f} seconds")

    state_counts = Counter(row['state'] for row in log_data if 'state' in row)
    state_time = defaultdict(float)
    for row in log_data:
        state_time[row.get('state','UNKNOWN')] += row.get('dt', 1/60.0)

    print("\nEngine State Distribution (by entry count):")
    for state, count in state_counts.most_common():
        print(f"  {state:<20}: {count} entries ({count/total_entries*100:.1f}%)")

    print("\nEngine State Distribution (by summed 'dt' time):")
    for state, time_spent in sorted(state_time.items(), key=lambda item: item[1], reverse=True):
        print(f"  {state:<20}: {time_spent:.2f} seconds")

    raw_throttle_values = [row['raw_throttle_input_pct'] for row in log_data if 'raw_throttle_input_pct' in row]
    if raw_throttle_values:
        print("\nRaw Throttle Input Statistics (from 'raw_throttle_input_pct'):")
        print(f"  Min raw throttle: {min(raw_throttle_values):.3f}")
        print(f"  Max raw throttle: {max(raw_throttle_values):.3f}")
        print(f"  Avg raw throttle: {sum(raw_throttle_values)/len(raw_throttle_values):.3f}")
    else:
        print("\nNo 'raw_throttle_input_pct' data found for statistics.")
        
    smoothed_throttle_values = [row['smoothed_throttle_pct'] for row in log_data if 'smoothed_throttle_pct' in row]
    if smoothed_throttle_values:
        print("\nSmoothed Throttle Input Statistics (from 'smoothed_throttle_pct'):")
        print(f"  Min smoothed throttle: {min(smoothed_throttle_values):.3f}")
        print(f"  Max smoothed throttle: {max(smoothed_throttle_values):.3f}")
        print(f"  Avg smoothed throttle: {sum(smoothed_throttle_values)/len(smoothed_throttle_values):.3f}")
    print("--- End General Statistics ---")

def analyze_throttle_anomalies(log_data, deadzone_low_arg, high_idle_throttle_threshold_arg): # Renamed args to avoid clash
    print(f"\n--- Throttle Anomaly Analysis (Raw Idle Throttle > {high_idle_throttle_threshold_arg*100:.0f}%) ---")
    anomalies_found = 0
    if not log_data:
        print("No data to analyze.")
        return

    for i, row in enumerate(log_data):
        current_state = row.get('state')
        raw_throttle = row.get('raw_throttle_input_pct', 0.0) 
        in_gesture = row.get('sim_in_pot_gesture', False)
        sfx_sound = row.get('sfx_chan_sound', 'None')
        is_non_gesture_sfx_playing = sfx_sound not in ['None', 'engine_idle_loop.wav'] and 'launch_control' not in sfx_sound

        if current_state == "IDLING" and raw_throttle > high_idle_throttle_threshold_arg and not in_gesture and not is_non_gesture_sfx_playing:
            anomalies_found += 1
            print(f"Potential raw throttle anomaly #{anomalies_found} at index {i}:")
            print(f"  State: {current_state}, Raw Throttle: {raw_throttle:.3f}, Smoothed: {row.get('smoothed_throttle_pct',0.0):.3f}, In Gesture: {in_gesture}, SFX: {sfx_sound}")
            print_log_excerpt(log_data, i, window=3, label=f"Throttle Anomaly {anomalies_found}")
            if anomalies_found >= 10:
                print("More anomalies found but output limited to 10.")
                break
    
    if anomalies_found == 0:
        print("No significant raw throttle anomalies found during IDLING state based on current criteria.")
    print("--- End Throttle Anomaly Analysis ---")


def analyze_light_blips(log_data, blip_cooldown_arg, rapid_blip_secs_threshold_arg): # Renamed args
    print(f"\n--- Light Blip Behavior Analysis (Expected Cooldown: {blip_cooldown_arg}s, Rapid Threshold: {rapid_blip_secs_threshold_arg}s) ---")
    if not log_data or len(log_data) < 2:
        print("Not enough data to analyze light blips.")
        return

    blip_trigger_events = []
    previous_blip_sim_time_from_log = 0.0 
    
    for i, row in enumerate(log_data):
        current_blip_sim_time_from_log = row.get('sim_last_blip_time', 0.0)

        if current_blip_sim_time_from_log > previous_blip_sim_time_from_log and \
           abs(current_blip_sim_time_from_log - previous_blip_sim_time_from_log) > 0.0001: 

            peak_throttle_for_this_blip_event = row.get('sim_peak_thr_gesture', 0.0)

            blip_trigger_events.append({
                "index": i,
                "log_timestamp": row.get('timestamp_unix', 0.0), 
                "sim_decision_time": current_blip_sim_time_from_log, 
                "peak_throttle_of_gesture": peak_throttle_for_this_blip_event, 
                "raw_throttle_at_log_entry": row.get('raw_throttle_input_pct', 0.0),
                "smoothed_throttle_at_log_entry": row.get('smoothed_throttle_pct', 0.0)
            })
        previous_blip_sim_time_from_log = current_blip_sim_time_from_log
        
    print(f"Found {len(blip_trigger_events)} distinct light blip trigger events (based on 'sim_last_blip_time' changes in the log).")

    if not blip_trigger_events:
        print("No light blip trigger events detected.")
        print("--- End Light Blip Behavior Analysis ---")
        return

    print("\nDetails of Light Blip Events:")
    for idx, event in enumerate(blip_trigger_events):
        print(f"  Event #{idx+1}: Log Index {event['index']}, "
              f"Log TS: {event['log_timestamp']:.3f}, "
              f"SimDecTS: {event['sim_decision_time']:.3f}, "
              f"PeakSmoothedThrottleInGesture: {event['peak_throttle_of_gesture']:.3f}, "
              f"RawThrottleAtLog: {event['raw_throttle_at_log_entry']:.3f}, "
              f"SmoothThrottleAtLog: {event['smoothed_throttle_at_log_entry']:.3f}")
        if event['peak_throttle_of_gesture'] > 0.40:
             print(f"    WARNING: Peak smoothed throttle {event['peak_throttle_of_gesture']:.3f} for this light blip event is > 0.40 (but should be <= 0.40 for light blips)!")
        print_log_excerpt(log_data, event['index'], window=2, label=f"Light Blip Event Detail {idx+1}")

    rapid_blip_sequences = 0
    for i in range(len(blip_trigger_events) - 1):
        event1 = blip_trigger_events[i]
        event2 = blip_trigger_events[i+1]
        
        time_diff_sim_decision = event2["sim_decision_time"] - event1["sim_decision_time"]
        time_diff_log_entry = event2["log_timestamp"] - event1["log_timestamp"]

        if time_diff_sim_decision < blip_cooldown_arg or time_diff_log_entry < rapid_blip_secs_threshold_arg:
            rapid_blip_sequences += 1
            print(f"\nPotential rapid/overlapping blip sequence #{rapid_blip_sequences} (between Event {i+1} and Event {i+2}):")
            print(f"  Time diff (sim_decision_time based): {time_diff_sim_decision:.4f}s")
            print(f"  Time diff (log timestamp based): {time_diff_log_entry:.4f}s")
            print_log_excerpt(log_data, event2['index'], window=3, label=f"Rapid Blip (Second in Pair) {rapid_blip_sequences}")
            
            if rapid_blip_sequences >= 10:
                print("More rapid blip sequences found but output limited to 10.")
                break
                
    if rapid_blip_sequences == 0 and len(blip_trigger_events) > 0 :
        print("\nNo overly rapid/overlapping light blip sequences found based on current criteria.")
    
    print("--- End Light Blip Behavior Analysis ---")

def main():
    parser = argparse.ArgumentParser(description="Analyze EV Sound Log CSV file.")
    parser.add_argument("csv_filepath", help="Path to the EV sound log CSV file (e.g., ev_sound_log.csv)")
    parser.add_argument("--deadzone", type=float, default=DEFAULT_THROTTLE_DEADZONE_LOW,
                        help=f"Throttle deadzone low (default: {DEFAULT_THROTTLE_DEADZONE_LOW})")
    parser.add_argument("--blip_cooldown", type=float, default=DEFAULT_LIGHT_BLIP_GESTURE_COOLDOWN,
                        help=f"Expected light blip gesture cooldown in seconds (default: {DEFAULT_LIGHT_BLIP_GESTURE_COOLDOWN})")
    parser.add_argument("--idle_anomaly_thresh", type=float, default=SUSPICIOUSLY_HIGH_IDLE_THROTTLE,
                        help=f"Throttle % above which is considered suspicious during IDLE (default: {SUSPICIOUSLY_HIGH_IDLE_THROTTLE})")
    parser.add_argument("--rapid_blip_thresh", type=float, default=RAPID_BLIP_THRESHOLD_SECONDS,
                        help=f"Time in seconds within which two blips are 'too rapid' (default: {RAPID_BLIP_THRESHOLD_SECONDS})")

    args = parser.parse_args()

    print(f"--- Starting Analysis of: {args.csv_filepath} ---")
    
    log_data = load_and_parse_csv(args.csv_filepath)

    if log_data:
        analyze_general_stats(log_data)
        analyze_throttle_anomalies(log_data, args.deadzone, args.idle_anomaly_thresh)
        analyze_light_blips(log_data, args.blip_cooldown, args.rapid_blip_thresh)
    else:
        print("Could not load or parse log data. Aborting analysis.")

    print("\n--- Analysis Complete ---")

if __name__ == "__main__":
    main()