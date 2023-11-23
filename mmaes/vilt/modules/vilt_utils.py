import torch
import torch.nn as nn
from transformers.optimization import AdamW
from transformers import (
    get_polynomial_decay_schedule_with_warmup,
    get_cosine_schedule_with_warmup,
)
from vilt.gadgets.my_metrics import VQAScore, Scalar, AVA_Accuracy, SRCC, LCC


def set_task(pl_module):
    pl_module.current_tasks = [
        k for k, v in pl_module.hparams.config["loss_names"].items() if v >= 1
    ]
    return


def test_ablation(pl_module, loss_name, res):
    test_ratio = pl_module.hparams.config['test_ratio']
    exp_name = pl_module.hparams.config["test_exp_name"]
    test_type = pl_module.hparams.config["test_type"]
    records = f'missing ratio: {test_ratio}, ' + res
    record_file = f'./records/{loss_name}/{loss_name}_{exp_name}_on_missing_{test_type}'
    with open(record_file, 'a+') as f:
        f.write(records+'\n')


def set_metrics(pl_module):
    for split in ["train", "val"]:
        for k, v in pl_module.hparams.config["loss_names"].items():
            if v <= 0:
                continue
            if k == "vqa":
                setattr(pl_module, f"{split}_vqa_score", VQAScore())
                setattr(pl_module, f"{split}_{k}_loss", Scalar())
            if k == "ava":
                setattr(pl_module, f"{split}_{k}_accuracy", AVA_Accuracy())
                setattr(pl_module, f"{split}_{k}_srcc", SRCC())
                setattr(pl_module, f"{split}_{k}_lcc", LCC())
                setattr(pl_module, f"{split}_{k}_loss", Scalar())


def epoch_wrapup(pl_module):
    phase = "train" if pl_module.training else "val"
    the_metric = 0

    for loss_name, v in pl_module.hparams.config["loss_names"].items():
        if v < 1:
            continue

        value = 0
        if loss_name == "vqa":
            value = getattr(pl_module, f"{phase}_{loss_name}_score").compute()
            pl_module.log(f"{loss_name}/{phase}/score_epoch", value)
            getattr(pl_module, f"{phase}_{loss_name}_score").reset()
            pl_module.log(
                f"{loss_name}/{phase}/loss_epoch",
                getattr(pl_module, f"{phase}_{loss_name}_loss").compute(),
            )
            getattr(pl_module, f"{phase}_{loss_name}_loss").reset()

        elif loss_name == "ava":
            value = getattr(pl_module, f"{phase}_{loss_name}_accuracy").compute()
            pl_module.log(f"{loss_name}/{phase}/accuracy_epoch", value)
            getattr(pl_module, f"{phase}_{loss_name}_accuracy").reset()

            value2 = getattr(pl_module, f"{phase}_{loss_name}_srcc").compute()
            pl_module.log(f"{loss_name}/{phase}/srcc_epoch", value2)
            getattr(pl_module, f"{phase}_{loss_name}_srcc").reset()

            value3 = getattr(pl_module, f"{phase}_{loss_name}_lcc").compute()
            pl_module.log(f"{loss_name}/{phase}/lcc_epoch", value3)
            getattr(pl_module, f"{phase}_{loss_name}_lcc").reset()

            pl_module.log(
                f"{loss_name}/{phase}/loss_epoch",
                getattr(pl_module, f"{phase}_{loss_name}_loss").compute(),
            )
            getattr(pl_module, f"{phase}_{loss_name}_loss").reset()


            if pl_module.hparams.config["test_exp_name"] is not None:
                res = 'Accuracy: {0:.2f}'.format(100*value)
                test_ablation(pl_module, loss_name, res)

        # if loss_name == "vqa":
        #     value = getattr(pl_module, f"{phase}_{loss_name}_score").compute()
        #     pl_module.log(f"{loss_name}/{phase}/score_epoch", value)
        #     getattr(pl_module, f"{phase}_{loss_name}_score").reset()
        #     pl_module.log(
        #         f"{loss_name}/{phase}/loss_epoch",
        #         getattr(pl_module, f"{phase}_{loss_name}_loss").compute(),
        #     )
        #     getattr(pl_module, f"{phase}_{loss_name}_loss").reset()
        #
        # else:
        #     value = getattr(pl_module, f"{phase}_{loss_name}_accuracy").compute()
        #     pl_module.log(f"{loss_name}/{phase}/accuracy_epoch", value)
        #     getattr(pl_module, f"{phase}_{loss_name}_accuracy").reset()
        #
        #     lcc = getattr(pl_module, f"{phase}_{loss_name}_lcc").compute()
        #     pl_module.log(f"{loss_name}/{phase}/lcc_epoch", value)
        #     getattr(pl_module, f"{phase}_{loss_name}_lcc").reset()
        #
        #     srcc = getattr(pl_module, f"{phase}_{loss_name}_srcc").compute()
        #     pl_module.log(f"{loss_name}/{phase}/srcc_epoch", value)
        #     getattr(pl_module, f"{phase}_{loss_name}_srcc").reset()
        #
        #     pl_module.log(f"{loss_name}/{phase}/loss_epoch",
        #                   getattr(pl_module, f"{phase}_{loss_name}_loss").compute(), )
        #     getattr(pl_module, f"{phase}_{loss_name}_loss").reset()
        #
        # the_metric += value
        # the_metric += lcc
        # the_metric += srcc

        the_metric += value
        pl_module.log(f"{phase}/the_metric", the_metric)


def set_schedule(pl_module):
    lr = pl_module.hparams.config["learning_rate"]
    wd = pl_module.hparams.config["weight_decay"]

    no_decay = [
        "bias",
        "LayerNorm.bias",
        "LayerNorm.weight",
        "norm.bias",
        "norm.weight",
        "norm1.bias",
        "norm1.weight",
        "norm2.bias",
        "norm2.weight",
    ]
    head_names = ["ava_classifier"]
    prompt_name = "prompt"
    lr_mult = pl_module.hparams.config["lr_mult"]
    end_lr = pl_module.hparams.config["end_lr"]
    decay_power = pl_module.hparams.config["decay_power"]
    optim_type = pl_module.hparams.config["optim_type"]

    names = [n for n, p in pl_module.named_parameters()]

    optimizer_grouped_parameters = [
        {
            "params": [
                p
                for n, p in pl_module.named_parameters()
                if not any(nd in n for nd in no_decay)
                   and not any(bb in n for bb in head_names)
            ],
            "weight_decay": wd,
            "lr": lr,
        },
        {
            "params": [
                p
                for n, p in pl_module.named_parameters()
                if any(nd in n for nd in no_decay)
                   and not any(bb in n for bb in head_names)
            ],
            "weight_decay": 0.0,
            "lr": lr,
        },
        {
            "params": [
                p
                for n, p in pl_module.named_parameters()
                if not any(nd in n for nd in no_decay)
                   and any(bb in n for bb in head_names)
            ],
            "weight_decay": wd,
            "lr": lr * lr_mult,
        },
        {
            "params": [
                p
                for n, p in pl_module.named_parameters()
                if any(nd in n for nd in no_decay) and any(bb in n for bb in head_names)
            ],
            "weight_decay": 0.0,
            "lr": lr * lr_mult,
        },
    ]

    if optim_type == "adamw":
        optimizer = AdamW(
            optimizer_grouped_parameters, lr=lr, eps=1e-8, betas=(0.9, 0.98)
        )
    elif optim_type == "adam":
        optimizer = torch.optim.Adam(optimizer_grouped_parameters, lr=lr)
    elif optim_type == "sgd":
        optimizer = torch.optim.SGD(optimizer_grouped_parameters, lr=lr, momentum=0.9)

    if pl_module.trainer.max_steps is None:
        max_steps = (
                len(pl_module.trainer.datamodule.train_dataloader())
                * pl_module.trainer.max_epochs
                // pl_module.trainer.accumulate_grad_batches
        )
    else:
        max_steps = pl_module.trainer.max_steps

    warmup_steps = pl_module.hparams.config["warmup_steps"]
    if isinstance(pl_module.hparams.config["warmup_steps"], float):
        warmup_steps = int(max_steps * warmup_steps)

    if decay_power == "cosine":
        scheduler = get_cosine_schedule_with_warmup(
            optimizer,
            num_warmup_steps=warmup_steps,
            num_training_steps=max_steps,
        )
    else:
        scheduler = get_polynomial_decay_schedule_with_warmup(
            optimizer,
            num_warmup_steps=warmup_steps,
            num_training_steps=max_steps,
            lr_end=end_lr,
            power=decay_power,
        )

    sched = {"scheduler": scheduler, "interval": "step"}

    return (
        [optimizer],
        [sched],
    )


class EMDLoss(nn.Module):
    def __init__(self):
        super(EMDLoss, self).__init__()

    def forward(self, p_target, p_estimate):
        assert p_target.shape == p_estimate.shape
        cdf_target = torch.cumsum(p_target, dim=1)
        cdf_estimate = torch.cumsum(p_estimate, dim=1)
        cdf_diff = cdf_estimate - cdf_target
        sample_wise_emd = torch.sqrt(torch.mean(torch.pow(torch.abs(cdf_diff), 2)))
        return sample_wise_emd
