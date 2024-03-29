"""
This variation just uses gumbel-softmax extension to get discrete actions.
This variation uses GRU as the agents rather than a flat MLP
"""

from collections import OrderedDict

import numpy as np
import torch
import torch.optim as optim
from torch import nn as nn

import marlkit.torch.pytorch_util as ptu
from marlkit.core.eval_util import create_stats_ordered_dict
from marlkit.torch.torch_rl_algorithm import MATorchTrainer


class DDPGTrainer(MATorchTrainer):
    """
    Deep Deterministic Policy Gradient
    """

    def __init__(
        self,
        qf,
        target_qf,
        policy,
        target_policy,
        discount=0.99,
        reward_scale=1.0,
        policy_learning_rate=1e-4,
        qf_learning_rate=1e-3,
        qf_weight_decay=0,
        target_hard_update_period=1000,
        tau=1e-2,
        use_soft_update=False,
        qf_criterion=None,
        policy_pre_activation_weight=0.0,
        optimizer_class=optim.Adam,
        min_q_value=-np.inf,
        max_q_value=np.inf,
        # mac stuff
        use_shared_experience=False,
        use_joint_space=False,  # for MADDPG
    ):
        super().__init__()
        if qf_criterion is None:
            qf_criterion = nn.MSELoss()
        self.qf = qf
        self.target_qf = target_qf
        self.policy = policy
        self.target_policy = target_policy
        self.use_shared_experience = use_shared_experience
        self.use_joint_space = use_joint_space

        self.discount = discount
        self.reward_scale = reward_scale

        self.policy_learning_rate = policy_learning_rate
        self.qf_learning_rate = qf_learning_rate
        self.qf_weight_decay = qf_weight_decay
        self.target_hard_update_period = target_hard_update_period
        self.tau = tau
        self.use_soft_update = use_soft_update
        self.qf_criterion = qf_criterion
        self.policy_pre_activation_weight = policy_pre_activation_weight
        self.min_q_value = min_q_value
        self.max_q_value = max_q_value

        self.qf_optimizer = optimizer_class(
            self.qf.parameters(),
            lr=self.qf_learning_rate,
        )
        self.policy_optimizer = optimizer_class(
            self.policy.parameters(),
            lr=self.policy_learning_rate,
        )

        self.eval_statistics = OrderedDict()
        self._n_train_steps_total = 0
        self._need_to_update_eval_statistics = True

    def train_from_torch(self, batch):
        rewards = batch["rewards"]
        terminals = batch["terminals"]
        obs = batch["observations"]
        actions = batch["actions"]
        next_obs = batch["next_observations"]
        states = batch["states"]
        next_states = batch["next_states"]

        """
        # since this is IPG paradigm, we can just stack everything and move on
        # since we're in the MA paradigm, we need to be careful of ragged
        # inputs...
        obs = torch.from_numpy(np.stack(obs, 0)).float()
        actions = torch.from_numpy(np.stack(actions, 0)).float()
        terminals = torch.from_numpy(np.stack(terminals, 0)).float()
        rewards = torch.from_numpy(np.stack(rewards, 0)).float()
        # states = torch.from_numpy(np.stack(states, 0)).float()
        next_obs = torch.from_numpy(np.stack(next_obs, 0)).float()
        # next_states = torch.from_numpy(np.stack(next_states, 0)).float()

        terminals = terminals.permute(0, 1, 3, 2)
        rewards = rewards.permute(0, 1, 3, 2)
        """

        """
        Policy operations.
        Do this via GRU!
        """
        if self.policy_pre_activation_weight > 0:
            raise NotImplemented
            """
            policy_actions, pre_tanh_value = self.policy(
                obs,
                return_preactivations=True,
            )
            pre_activation_policy_loss = (pre_tanh_value ** 2).sum(dim=1).mean()
            q_output = self.qf(obs, policy_actions)
            raw_policy_loss = -q_output.mean()
            policy_loss = raw_policy_loss + pre_activation_policy_loss * self.policy_pre_activation_weight
            """

        # else:
        #     policy_actions = self.policy(obs)
        #     flat_inputs = torch.cat([obs, policy_actions], dim=-1)
        #     q_output = self.qf(flat_inputs)
        #     raw_policy_loss = policy_loss = -q_output.mean()

        # do the equivalent of self.policy(obs) here
        policy_actions = []
        batch_num = len(obs)
        for batch in range(batch_num):
            size = obs[batch].shape[1]
            path_len = obs[batch].shape[0]
            hidden = torch.cat(self.policy.init_hidden(size), 0)
            policy_action = []
            for t in range(path_len):
                pol_act, hidden = self.policy(torch.from_numpy(obs[batch][t, :, :]).float(), hidden)
                policy_action.append(pol_act)
            policy_actions.append(torch.stack(policy_action, 0))
        policy_actions = torch.stack(policy_actions, 0)

        f_obs = torch.from_numpy(np.stack(obs, 0)).float()
        if self.use_joint_space:
            n_agents = policy_actions.shape[-2]
            rep_policy_actions = policy_actions.detach().repeat(1, 1, 1, n_agents)
            rep_states = torch.from_numpy(np.stack(states, 0)).float().repeat(1, 1, n_agents, 1)
            flat_inputs = torch.cat([f_obs, policy_actions, rep_policy_actions, rep_states], dim=-1)
        else:
            flat_inputs = torch.cat([f_obs, policy_actions], dim=-1)
        q_output = self.qf(flat_inputs)
        raw_policy_loss = policy_loss = -q_output.mean()

        """
        Critic operations.
        """
        next_actions = []
        batch_num = len(next_obs)
        for batch in range(batch_num):
            size = next_obs[batch].shape[1]
            path_len = next_obs[batch].shape[0]
            hidden = torch.cat(self.target_policy.init_hidden(size), 0)
            next_action = []
            for t in range(path_len):
                next_act, hidden = self.target_policy(torch.from_numpy(next_obs[batch][t, :, :]).float(), hidden)
                next_action.append(next_act)
            next_actions.append(torch.stack(next_action, 0))
        next_actions = torch.stack(next_actions, 0)
        # speed up computation by not backpropping these gradients
        next_actions.detach()
        f_next_obs = torch.from_numpy(np.stack(next_obs, 0)).float()
        if self.use_joint_space:
            n_agents = next_actions.shape[-2]
            rep_next_actions = next_actions.repeat(1, 1, 1, n_agents)
            rep_next_states = torch.from_numpy(np.stack(next_states, 0)).float().repeat(1, 1, n_agents, 1)
            flat_inputs = torch.cat([f_next_obs, next_actions, rep_next_actions, rep_next_states], -1)
        else:
            flat_inputs = torch.cat([f_next_obs, next_actions], -1)
        target_q_values = self.target_qf(flat_inputs)

        """
        next_actions = self.target_policy(next_obs)
        # speed up computation by not backpropping these gradients
        next_actions.detach()
        flat_inputs = torch.cat([next_obs, next_actions], -1)
        target_q_values = self.target_qf(flat_inputs)
        """
        t_rewards = torch.from_numpy(np.stack(rewards, 0)).float().permute(0, 1, 3, 2)
        t_terminals = torch.from_numpy(np.stack(terminals, 0)).float().permute(0, 1, 3, 2)
        t_obs = torch.from_numpy(np.stack(obs, 0)).float()
        t_actions = torch.from_numpy(np.stack(actions, 0)).float()

        q_target = t_rewards + (1.0 - t_terminals) * self.discount * target_q_values
        q_target = q_target.detach()
        q_target = torch.clamp(q_target, self.min_q_value, self.max_q_value)
        if self.use_joint_space:
            n_agents = t_actions.shape[-2]
            rep_actions = t_actions.repeat(1, 1, 1, n_agents)
            rep_states = torch.from_numpy(np.stack(states, 0)).float().repeat(1, 1, n_agents, 1)
            flat_inputs = torch.cat([t_obs, t_actions, rep_actions, rep_states], -1)
        else:
            flat_inputs = torch.cat([t_obs, t_actions], -1)
        q_pred = self.qf(flat_inputs)
        bellman_errors = (q_pred - q_target) ** 2
        raw_qf_loss = self.qf_criterion(q_pred, q_target)

        if self.qf_weight_decay > 0:
            reg_loss = self.qf_weight_decay * sum(torch.sum(param ** 2) for param in self.qf.regularizable_parameters())
            qf_loss = raw_qf_loss + reg_loss
        else:
            qf_loss = raw_qf_loss

        """
        Update Networks
        """

        self.policy_optimizer.zero_grad()
        policy_loss.backward()
        self.policy_optimizer.step()

        self.qf_optimizer.zero_grad()
        qf_loss.backward()
        self.qf_optimizer.step()

        self._update_target_networks()

        """
        Save some statistics for eval using just one batch.
        """
        if self._need_to_update_eval_statistics:
            self._need_to_update_eval_statistics = False
            self.eval_statistics["QF Loss"] = np.mean(ptu.get_numpy(qf_loss))
            self.eval_statistics["Policy Loss"] = np.mean(ptu.get_numpy(policy_loss))
            self.eval_statistics["Raw Policy Loss"] = np.mean(ptu.get_numpy(raw_policy_loss))
            self.eval_statistics["Preactivation Policy Loss"] = (
                self.eval_statistics["Policy Loss"] - self.eval_statistics["Raw Policy Loss"]
            )
            self.eval_statistics.update(
                create_stats_ordered_dict(
                    "Q Predictions",
                    ptu.get_numpy(q_pred),
                )
            )
            self.eval_statistics.update(
                create_stats_ordered_dict(
                    "Q Targets",
                    ptu.get_numpy(q_target),
                )
            )
            self.eval_statistics.update(
                create_stats_ordered_dict(
                    "Bellman Errors",
                    ptu.get_numpy(bellman_errors),
                )
            )
            self.eval_statistics.update(
                create_stats_ordered_dict(
                    "Policy Action",
                    ptu.get_numpy(policy_actions),
                )
            )
        self._n_train_steps_total += 1

    def _update_target_networks(self):
        if self.use_soft_update:
            ptu.soft_update_from_to(self.policy, self.target_policy, self.tau)
            ptu.soft_update_from_to(self.qf, self.target_qf, self.tau)
        else:
            if self._n_train_steps_total % self.target_hard_update_period == 0:
                ptu.copy_model_params_from_to(self.qf, self.target_qf)
                ptu.copy_model_params_from_to(self.policy, self.target_policy)

    def get_diagnostics(self):
        return self.eval_statistics

    def end_epoch(self, epoch):
        self._need_to_update_eval_statistics = True

    @property
    def networks(self):
        return [
            self.policy,
            self.qf,
            self.target_policy,
            self.target_qf,
        ]

    def get_epoch_snapshot(self):
        return dict(
            qf=self.qf,
            target_qf=self.target_qf,
            trained_policy=self.policy,
            target_policy=self.target_policy,
        )
