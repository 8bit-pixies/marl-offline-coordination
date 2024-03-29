"""
Run DQN on grid world.
"""
import sys
import os

sys.path.append(os.path.dirname(sys.path[0]))

import argparse
import gym
from torch import nn as nn

from marlkit.exploration_strategies.base import PolicyWrappedWithExplorationStrategy
from marlkit.torch.networks import Mlp
import marlkit.torch.pytorch_util as ptu
from marlkit.launchers.launcher_util import setup_logger

from marlkit.torch.dqn.ma_mixer import COMATrainer

# COMA
from marlkit.policies.argmax import MAArgmaxDiscretePolicy
from marlkit.torch.extra_networks import COMACritic

# use the MARL versions!
from marlkit.torch.torch_marl_algorithm import TorchBatchMARLAlgorithm
from marlkit.exploration_strategies.epsilon_greedy import MAEpsilonGreedy
from marlkit.samplers.data_collector.marl_path_collector import MdpPathCollector
from marlkit.data_management.env_replay_buffer import (
    MAEnvReplayBuffer,
    FullMAEnvReplayBuffer,
)
from marlkit.policies.argmax import MAArgmaxDiscretePolicy
from marlkit.policies.recurrent import RecurrentPolicy


import numpy as np
from experiment.env import ENV_LOOKUP


def experiment(variant, train="pursuit", test="pursuit"):
    expl_env = ENV_LOOKUP[train]
    eval_env = ENV_LOOKUP[test]

    obs_dim = expl_env.multi_agent_observation_space["obs"].low.size
    action_dim = expl_env.multi_agent_action_space.n
    n_agents = expl_env.max_num_agents
    max_agents = eval_env.max_num_agents
    state_shape = eval_env.global_observation_space.low.size

    M = variant["layer_size"]
    # N = variant["layer_mixer_size"]
    N = variant["layer_size"]

    qf = Mlp(
        hidden_sizes=[M, M, M],
        input_size=obs_dim,
        output_size=action_dim,
    )
    target_qf = Mlp(
        hidden_sizes=[M, M, M],
        input_size=obs_dim,
        output_size=action_dim,
    )
    critic = COMACritic(
        n_agents=n_agents,
        action_size=action_dim,
        obs_shape=obs_dim,
        state_shape=state_shape,
        mixing_embed_dim=N,
    )
    target_critic = COMACritic(
        n_agents=n_agents,
        action_size=action_dim,
        obs_shape=obs_dim,
        state_shape=state_shape,
        mixing_embed_dim=N,
    )
    qf_criterion = nn.MSELoss()
    eval_policy = MAArgmaxDiscretePolicy(qf)
    expl_policy = PolicyWrappedWithExplorationStrategy(
        MAEpsilonGreedy(expl_env.multi_agent_action_space, n_agents),
        eval_policy,
    )
    eval_path_collector = MdpPathCollector(
        eval_env,
        eval_policy,
    )
    expl_path_collector = MdpPathCollector(
        expl_env,
        expl_policy,
    )

    trainer = COMATrainer(
        qf=qf,
        target_qf=target_qf,
        qf_criterion=qf_criterion,
        critic=critic,
        target_critic=target_critic,
        **variant["trainer_kwargs"],
    )
    replay_buffer = FullMAEnvReplayBuffer(
        variant["replay_buffer_size"],
        expl_env,
    )
    algorithm = TorchBatchMARLAlgorithm(
        trainer=trainer,
        exploration_env=expl_env,
        evaluation_env=eval_env,
        exploration_data_collector=expl_path_collector,
        evaluation_data_collector=eval_path_collector,
        replay_buffer=replay_buffer,
        **variant["algorithm_kwargs"],
    )
    print(algorithm)
    algorithm.to(ptu.device)
    algorithm.train()


def run(train, test):
    # noinspection PyTypeChecker
    base_agent_size = 64
    mixer_size = 32
    num_epochs = 1000
    buffer_size = 32
    max_path_length = 500
    eval_discard_incomplete = False if test in ["kaz"] else True

    variant = dict(
        algorithm="COMA",
        version="normal",
        layer_size=base_agent_size,
        layer_mixer_size=mixer_size,
        replay_buffer_size=buffer_size,
        algorithm_kwargs=dict(
            num_epochs=num_epochs,
            num_eval_steps_per_epoch=max_path_length * 5,
            num_trains_per_train_loop=10,
            num_expl_steps_per_train_loop=max_path_length * 5,
            min_num_steps_before_training=1000,
            max_path_length=max_path_length,
            batch_size=32,  # this is number of episodes - not samples!
            eval_discard_incomplete=eval_discard_incomplete,
        ),
        trainer_kwargs=dict(
            discount=0.99,
            learning_rate=3e-4,
        ),
    )

    if test is None:
        test = train
    setup_logger(f"{train}-{test}-coma", variant=variant)
    # ptu.set_gpu_mode(True)  # optionally set the GPU (default=False)
    experiment(variant, train, test)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="runner")
    parser.add_argument("--train", type=str, default="pursuit")
    parser.add_argument("--test", type=str, default="pursuit")
    args = parser.parse_args()
    train = args.train
    test = args.test
    run(train, test)
