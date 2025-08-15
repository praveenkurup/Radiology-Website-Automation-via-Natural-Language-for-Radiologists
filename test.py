def compute_slider_delta(increment_mode: int, target_value: int, current_value: int) -> int:
    if increment_mode == 0:
        # Absolute mode: go to a specific value
        return target_value - current_value
    else:
        # Relative mode: move by a certain number of steps
        return target_value

# Examples:
print(compute_slider_delta(0, 50, 30))  # → 20 (go to 50 from 30)
print(compute_slider_delta(1, 20, 30))  # → 20 (increase by 20)
print(compute_slider_delta(0, 15, 20))  # → -5 (go to 15 from 20)
