import gzip
import json
import sys
from collections import defaultdict


def assign_lanes(events):
    """
    Greedy lane assignment: assign each event to the lowest lane
    where it doesn't overlap with the previous event on that lane.
    Events must be sorted by start time.
    Returns a list of lane indices (0-based).
    """
    # lane_ends[i] = end timestamp of last event assigned to lane i
    lane_ends = []
    lanes = []
    for e in events:
        ts = e["ts"]
        assigned = None
        for i, end in enumerate(lane_ends):
            if ts >= end:
                assigned = i
                break
        if assigned is None:
            assigned = len(lane_ends)
            lane_ends.append(0)
        lane_ends[assigned] = ts + e.get("dur", 0)
        lanes.append(assigned)
    return lanes


def fix_trace(input_path, output_path):
    print(f"Reading {input_path}...")
    if input_path.endswith(".gz"):
        with gzip.open(input_path, "rt") as f:
            data = json.load(f)
    else:
        with open(input_path, "r") as f:
            data = json.load(f)

    events = data["traceEvents"]
    print(f"Total events: {len(events)}")

    # Identify GPU stream tracks: events with cat in (kernel, gpu_memcpy) on tid=19
    # Group duration events by (pid, tid)
    gpu_dur_cats = {"kernel", "gpu_memcpy"}
    gpu_groups = defaultdict(list)  # (pid, tid) -> [(index_in_events, event)]
    for i, e in enumerate(events):
        if e.get("cat") in gpu_dur_cats:
            key = (e["pid"], e["tid"])
            gpu_groups[key].append((i, e))

    # Collect ac2g flow-end events by (pid, tid)
    ac2g_groups = defaultdict(list)  # (pid, tid) -> [(index_in_events, event)]
    for i, e in enumerate(events):
        if e.get("cat") == "ac2g" and e.get("ph") == "f":
            key = (e["pid"], e["tid"])
            ac2g_groups[key].append((i, e))

    # Collect gpu_user_annotation events by (pid, tid)
    annotation_groups = defaultdict(list)
    for i, e in enumerate(events):
        if e.get("cat") == "gpu_user_annotation":
            key = (e["pid"], e["tid"])
            annotation_groups[key].append((i, e))

    total_moved = 0
    new_metadata = []

    for (pid, tid), indexed_events in gpu_groups.items():
        # Sort by start time
        indexed_events.sort(key=lambda x: x[1]["ts"])
        evts = [e for _, e in indexed_events]
        indices = [i for i, _ in indexed_events]

        # Assign lanes
        lanes = assign_lanes(evts)
        max_lane = max(lanes) if lanes else 0

        if max_lane == 0:
            continue  # No overlaps in this group

        # Build ts -> lane mapping for ac2g matching
        ts_to_lane = {}
        for evt, lane in zip(evts, lanes):
            if lane > 0:
                ts_to_lane[evt["ts"]] = lane

        moved_in_group = sum(1 for l in lanes if l > 0)
        total_moved += moved_in_group

        # Generate new tids for lanes > 0
        # Use tid * 1000 + lane as the new tid to avoid collisions
        for idx, lane in zip(indices, lanes):
            if lane > 0:
                new_tid = tid * 1000 + lane
                events[idx]["tid"] = new_tid

        # Move corresponding ac2g flow-end events
        if (pid, tid) in ac2g_groups:
            for idx, e in ac2g_groups[(pid, tid)]:
                lane = ts_to_lane.get(e["ts"], 0)
                if lane > 0:
                    new_tid = tid * 1000 + lane
                    events[idx]["tid"] = new_tid

        # Move gpu_user_annotation events that overlap with moved kernels
        # These are typically duration events too
        if (pid, tid) in annotation_groups:
            for idx, e in annotation_groups[(pid, tid)]:
                if e.get("ph") == "X" and "dur" in e:
                    lane = ts_to_lane.get(e["ts"], 0)
                    if lane > 0:
                        new_tid = tid * 1000 + lane
                        events[idx]["tid"] = new_tid

        # Add thread_name metadata for new lanes
        for lane in range(1, max_lane + 1):
            new_tid = tid * 1000 + lane
            new_metadata.append({
                "ph": "M",
                "name": "thread_name",
                "pid": pid,
                "tid": new_tid,
                "args": {"name": f"stream {tid} (overflow {lane})"},
            })
            new_metadata.append({
                "ph": "M",
                "name": "thread_sort_index",
                "pid": pid,
                "tid": new_tid,
                "args": {"sort_index": tid * 1000 + lane},
            })

    events.extend(new_metadata)
    data["traceEvents"] = events

    print(f"Moved {total_moved} overlapping events to separate tracks")
    print(f"Added {len(new_metadata)} metadata events for new tracks")

    print(f"Writing {output_path}...")
    if output_path.endswith(".gz"):
        with gzip.open(output_path, "wt") as f:
            json.dump(data, f)
    else:
        with open(output_path, "w") as f:
            json.dump(data, f)

    print("Done.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        input_path = "combined_trace.json.gz"
    else:
        input_path = sys.argv[1]

    if len(sys.argv) < 3:
        # Default output: add _fixed suffix
        base = input_path.replace(".json.gz", "").replace(".json", "")
        if input_path.endswith(".json.gz"):
            output_path = base + "_fixed.json.gz"
        else:
            output_path = base + "_fixed.json"
    else:
        output_path = sys.argv[2]

    fix_trace(input_path, output_path)

