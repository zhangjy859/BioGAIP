# demo.py
import collections
import unittest
from typing import Deque, Tuple

class DecayingReward:
    def __init__(
        self,
        initial_reward: float,
        decay_rate: float = 0.9,
        slow_decay_rate: float = 0.99,
        recovery_step: float = 0.15,
        cooldown_period: int = 10,
        window_a: int = 15,
        min_triggers_a: int = 3,
        window_b: int = 30,
        min_pattern_len: int = 3
    ):
        self.initial_reward = initial_reward
        self.decay_rate = decay_rate
        self.slow_decay_rate = slow_decay_rate
        self.recovery_step = recovery_step
        self.cooldown_period = cooldown_period
        self.window_a = window_a
        self.min_triggers_a = min_triggers_a
        self.window_b = window_b
        self.min_pattern_len = min_pattern_len
        self.reset()

    def reset(self) -> None:
        self.current_reward = float(self.initial_reward)
        self.clock = 0
        self.history: Deque[Tuple[int, str]] = collections.deque()
        self.cooldown_until = 0

    def timer(self) -> None:
        self.clock += 1

    def __call__(self, category: str) -> int:
        self.history.append((self.clock, category))
        self._maintain_history()
        self._evaluate_recovery()
        
        output_reward = round(self.current_reward)
        
        if output_reward == 0:
            self.current_reward *= self.slow_decay_rate
        else:
            self.current_reward *= self.decay_rate
            
        return output_reward

    def _maintain_history(self) -> None:
        while self.history and self.history[0][0] <= self.clock - self.window_b:
            self.history.popleft()

    def _evaluate_recovery(self) -> None:
        if self.clock <= self.cooldown_until:
            return

        recent_triggers_a = sum(1 for tick, _ in self.history if tick > self.clock - self.window_a)
        if recent_triggers_a < self.min_triggers_a:
            return

        recent_b = list(self.history)
        max_len = 0
        n = len(recent_b)

        for i in range(n - self.min_pattern_len + 1):
            cat = recent_b[i][1]
            if recent_b[i + 1][1] != cat:
                continue

            interval = recent_b[i + 1][0] - recent_b[i][0]
            curr_len = 2
            
            for j in range(i + 2, n):
                if recent_b[j][1] == cat and recent_b[j][0] - recent_b[j - 1][0] == interval:
                    curr_len += 1
                else:
                    break
                    
            if curr_len >= self.min_pattern_len and recent_b[i + curr_len - 1][0] == self.clock:
                max_len = max(max_len, curr_len)

        if max_len >= self.min_pattern_len:
            recovery_amount = self.initial_reward * (max_len * self.recovery_step)
            self.current_reward = min(self.initial_reward, self.current_reward + recovery_amount)
            self.cooldown_until = self.clock + self.cooldown_period


class TestDecayingReward(unittest.TestCase):
    def test_decay_and_slow_decay(self):
        reward = DecayingReward(initial_reward=10, decay_rate=0.5, slow_decay_rate=0.9)
        results = [reward("A") for _ in range(7)]
        
        self.assertEqual(results[0], 10)
        self.assertEqual(results[-1], 0)
        self.assertGreater(reward.current_reward, 0)
        
    def test_reset(self):
        reward = DecayingReward(initial_reward=100)
        reward("A")
        reward.timer()
        reward.reset()
        
        self.assertEqual(reward.clock, 0)
        self.assertEqual(reward.current_reward, 100.0)
        self.assertEqual(len(reward.history), 0)

    def test_timer(self):
        reward = DecayingReward(initial_reward=100)
        reward.timer()
        reward.timer()
        
        self.assertEqual(reward.clock, 2)

    def test_recovery_and_cooldown(self):
        reward = DecayingReward(
            initial_reward=100, 
            decay_rate=0.5, 
            recovery_step=0.2,
            cooldown_period=10
        )
        
        reward.timer()
        r1 = reward("A")
        
        reward.timer()
        reward.timer()
        r2 = reward("A")
        
        reward.timer()
        reward.timer()
        r3 = reward("A")
        
        self.assertEqual(r1, 100)
        self.assertEqual(r2, 50)
        self.assertEqual(r3, 85)
        
        reward.timer()
        reward.timer()
        r4 = reward("A")
        
        reward.timer()
        reward.timer()
        r5 = reward("A")
        
        reward.timer()
        reward.timer()
        r6 = reward("A")
        
        self.assertLess(r6, 20)
        
        for _ in range(6):
            reward.timer()
            
        r7 = reward("A")
        
        reward.timer()
        reward.timer()
        r8 = reward("A")
        
        reward.timer()
        reward.timer()
        r9 = reward("A")
        
        self.assertGreater(r9, r8)

if __name__ == '__main__':
    unittest.main()