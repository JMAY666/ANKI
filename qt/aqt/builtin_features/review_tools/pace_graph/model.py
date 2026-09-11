# Source integration: Ankitects Pty Ltd and contributors
"""Rolling answer pace, including a live penalty for an overdue current card."""
from collections import deque
import math


class Pace:
    def __init__(self, goal=10.0, window=20):
        self.goal = goal
        self.window = window
        self.answers = deque(maxlen=window)
        self.current = None
        self.paused = False
        self.flipped = False

    def question(self):
        self.current = 0.0
        self.flipped = False

    def flip(self):
        self.flipped = True

    def advance(self, seconds, studying):
        if self.current is not None and not self.paused and not self.flipped and studying and 0 <= seconds <= 2:
            self.current += seconds

    def answer(self):
        if self.current is not None:
            if not self.paused:
                self.answers.append(self.current)
            self.current = None

    def average(self):
        if not self.answers:
            return None
        average = sum(self.answers) / len(self.answers)
        # Starting a fresh card cannot artificially improve the score.
        # An overdue card gradually worsens it before it is answered.
        extra = max(0, (self.current or 0) - average)
        return average + extra / len(self.answers)

    def delta(self):
        average = self.average()
        return None if average is None else self.goal - average


class SmoothPace:
    """Continuous exponential easing; transition seconds is time to settle 95%."""
    def __init__(self, seconds=4):
        self.seconds = seconds
        self.value = None

    def advance(self, target, dt):
        if target is None:
            return self.value
        if self.value is None:
            self.value = 0.0
        if 0 < dt <= 2:
            self.value += (target - self.value) * (-math.expm1(-3 * dt / self.seconds))
        return self.value
