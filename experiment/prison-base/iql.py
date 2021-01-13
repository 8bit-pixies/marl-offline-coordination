"""
This script shows an example of how to run QMIX style environments:

*  QMIX
*  MAVEN (possible in theory, not complete)
*  VDN
*  IQN

where GRU is not used. This is probably when we used stacked frames instead, 
e.g. for atari style environments?
"""
import sys
import os

sys.path.append(os.path.dirname(sys.path[0]))
import gym
from torch import nn as nn

from marlkit.exploration_strategies.base import PolicyWrappedWithExplorationStrategy
from marlkit.torch.dqn.ma_mixer import DoubleDQNTrainer
from marlkit.torch.networks import Mlp
import marlkit.torch.pytorch_util as ptu
from marlkit.torch.mixers import VDNMixer, QMixer
from marlkit.launchers.launcher_util import setup_logger
from marlkit.policies.argmax import MAArgmaxDiscretePolicy


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
from supersuit import (
    resize_v0,
    color_reduction_v0,
    flatten_v0,
    normalize_obs_v0,
    dtype_v0,
    pad_observations_v0,
    pad_action_space_v0,
)
from pettingzoo.butterfly import prison_v2
from marlkit.envs.wrappers import MultiAgentEnv

resize_size = 32
env_wrapper = lambda x: flatten_v0(
    normalize_obs_v0(
        dtype_v0(
            pad_observations_v0(
                pad_action_space_v0(
                    resize_v0(color_reduction_v0(x), resize_size, resize_size),
                )
            ),
            np.float32,
        )
    )
)


def experiment(variant):
    expl_env = MultiAgentEnv(env_wrapper(prison_v2.parallel_env()))
    eval_env = MultiAgentEnv(env_wrapper(prison_v2.parallel_env()))
    obs_dim = expl_env.multi_agent_observation_space["obs"].low.size
    action_dim = expl_env.multi_agent_action_space.n
    n_agents = expl_env.max_num_agents

    M = variant["layer_size"]

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

    # needs: mixer = , target_mixer =
    mixer = None
    target_mixer = None

    trainer = DoubleDQNTrainer(
        qf=qf,
        target_qf=target_qf,
        qf_criterion=qf_criterion,
        mixer=mixer,
        target_mixer=target_mixer,
        use_shared_experience=False,
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
    algorithm.to(ptu.device)
    algorithm.train()


def test():
    # noinspection PyTypeChecker
    base_agent_size = 64
    mixer_size = 32
    num_epochs = 10000
    buffer_size = 32

    variant = dict(
        algorithm="IQL",
        version="normal",
        layer_size=base_agent_size,
        replay_buffer_size=buffer_size,
        algorithm_kwargs=dict(
            num_epochs=num_epochs,
            num_eval_steps_per_epoch=32,
            num_trains_per_train_loop=32,
            num_expl_steps_per_train_loop=32,
            min_num_steps_before_training=32,
            max_path_length=900,
            batch_size=32,  # this is number of episodes - not samples!
        ),
        trainer_kwargs=dict(
            discount=0.99,
            learning_rate=3e-4,
        ),
    )

    setup_logger(f"prison-iql", variant=variant)
    # ptu.set_gpu_mode(True)  # optionally set the GPU (default=False)
    experiment(variant)


if __name__ == "__main__":
    test()
