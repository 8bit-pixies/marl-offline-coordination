"""
Torch argmax policy
"""
import numpy as np
from torch import nn

import marlkit.torch.pytorch_util as ptu
from marlkit.policies.base import Policy


class ArgmaxDiscretePolicy(nn.Module, Policy):
    def __init__(self, qf):
        super().__init__()
        self.qf = qf

    def get_action(self, obs):
        obs = np.expand_dims(obs, axis=0)
        print(obs)
        obs = ptu.from_numpy(obs).float()
        q_values = self.qf(obs).squeeze(0)
        q_values_np = ptu.get_numpy(q_values)
        return q_values_np.argmax(), {}


class MAArgmaxDiscretePolicy(nn.Module, Policy):
    def __init__(self, qf):
        super().__init__()
        self.qf = qf

    def get_action_(self, obs):
        obs = np.expand_dims(obs, axis=0)
        obs = ptu.from_numpy(obs).float()
        q_values = self.qf(obs).squeeze(0)
        q_values_np = ptu.get_numpy(q_values)
        return q_values_np.argmax(), {}

    def get_action(self, obs):
        if type(obs) is list:
            # we're in MARL land...
            actions = []
            for obs_dict in obs:
                actions.append(self.get_action_(obs_dict["obs"])[0])
            return actions, {}
        else:
            obs = np.expand_dims(obs, axis=0)
            obs = ptu.from_numpy(obs).float()
            q_values = self.qf(obs).squeeze(0)
            q_values_np = ptu.get_numpy(q_values)
            return q_values_np.argmax(), {}
