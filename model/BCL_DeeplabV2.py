import torch.nn as nn
import numpy as np
import math
import torch
import torch.nn.functional as F


affine_par = True
# from torch.cuda.amp import autocast


def freeze_bn(net):
    for module in net.modules():
        if isinstance(module, torch.nn.modules.BatchNorm2d):
            for i in module.parameters():
                i.requires_grad = False


def release_bn(net):
    for module in net.modules():
        if isinstance(module, torch.nn.modules.BatchNorm2d):
            for i in module.parameters():
                i.requires_grad = True


def conv3x3(in_planes, out_planes, stride=1):
    "3x3 convolution with padding"
    return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                     padding=1, bias=False)


class Bottleneck(nn.Module):
    expansion = 4

    def __init__(self, inplanes, planes, stride=1, dilation=1, downsample=None):
        super(Bottleneck, self).__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=1, stride=stride, bias=False)  # change
        self.bn1 = nn.BatchNorm2d(planes, affine=affine_par)
        for i in self.bn1.parameters():
            i.requires_grad = False

        padding = dilation
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3, stride=1,  # change
                               padding=padding, bias=False, dilation=dilation)
        self.bn2 = nn.BatchNorm2d(planes, affine=affine_par)
        for i in self.bn2.parameters():
            i.requires_grad = False
        self.conv3 = nn.Conv2d(planes, planes * 4, kernel_size=1, bias=False)
        self.bn3 = nn.BatchNorm2d(planes * 4, affine=affine_par)
        for i in self.bn3.parameters():
            i.requires_grad = False
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out


class Classifier_Module(nn.Module):
    def __init__(self, inplanes, dilation_series, padding_series, num_classes):
        super(Classifier_Module, self).__init__()
        self.conv2d_list = nn.ModuleList()
        for dilation, padding in zip(dilation_series, padding_series):
            self.conv2d_list.append(
                nn.Conv2d(inplanes, num_classes, kernel_size=3, stride=1, padding=padding, dilation=dilation,
                          bias=True))

        for m in self.conv2d_list:
            m.weight.data.normal_(0, 0.01)

    def forward(self, x):
        out = self.conv2d_list[0](x)
        feature = self.conv2d_list[0](x)
        for i in range(len(self.conv2d_list) - 1):
            feature = torch.cat((feature, self.conv2d_list[i + 1](x)), dim=1)
            out += self.conv2d_list[i + 1](x)
        return out, feature


class ResNetPair5(nn.Module):
    def __init__(self, block=Bottleneck, layers=(3, 4, 23, 3), num_classes=19):
        """
        the DeeplabV2 model constructor
        @param block: the block network used as a component in the DeeplabV2
        @param layers: the number of channels for each layer
        @param num_classes: the number of classes for the output
        @param multiscale: deprecated
        """
        self.inplanes = 64
        super(ResNetPair5, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3,
                               bias=False)
        self.bn1 = nn.BatchNorm2d(64, affine=affine_par)

        for i in self.bn1.parameters():
            i.requires_grad = False

        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1, ceil_mode=True)  # change
        self.layer1 = self._make_layer(block, 64, layers[0])
        self.layer2 = self._make_layer(block, 128, layers[1], stride=2)
        self.layer3 = self._make_layer(block, 256, layers[2], stride=1, dilation=2)
        self.layer4 = self._make_layer(block, 512, layers[3], stride=1, dilation=4)
        self.layer5 = self._make_pred_layer(Classifier_Module, 2048, [6, 12, 18, 24], [6, 12, 18, 24], num_classes)
        # self.layer6 = self._make_pred_layer(Classifier_Module, 2048, [6, 12, 18, 24], [6, 12, 18, 24], num_classes)
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                # n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, 0.01)

    def _make_layer(self, block=Bottleneck, planes=64, blocks=3, stride=1, dilation=1):
        """
        @param block: the block network use as the component of the layer
        @param planes: the basic number of filters
        @param blocks:
        @param stride:
        @param dilation:
        @return:
        """
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion or dilation == 2 or dilation == 4:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * block.expansion, affine=affine_par))
        for i in downsample._modules['1'].parameters():
            i.requires_grad = False

        layers = []
        layers.append(block(self.inplanes, planes, stride, dilation=dilation, downsample=downsample))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes, dilation=dilation))
        return nn.Sequential(*layers)
        #return SublinearSequential(*list(layers.children()))

    def _make_pred_layer(self, block, inplanes, dilation_series, padding_series, num_classes):
        return block(inplanes, dilation_series, padding_series, num_classes)

    def forward(self, x, source=False):
        N, C, H, W = x.shape
        x = self.conv1(x)  # N, 64, 112, 112
        x = self.bn1(x)
        x = self.relu(x)  # N, 64, 112, 112
        x = self.maxpool(x)  # N, 64, 57, 57
        x = self.layer1(x)  # N, 64, 57, 57
        x = self.layer2(x)  # N, 512, 29, 29
        x = self.layer3(x)  # N, 1024, 29, 29
        x = self.layer4(x)  # N, 2048, 29, 29
        x1, feature = self.layer5(x)  # N, #classes, 29, 29
        x1 = F.interpolate(x1, (H, W), mode='bilinear', align_corners=True)

        return x1, feature

    def get_1x_lr_params_NOscale(self):
        b = []
        b.append(self.conv1)
        b.append(self.bn1)
        b.append(self.layer1)
        b.append(self.layer2)
        b.append(self.layer3)
        b.append(self.layer4)
        for i in range(len(b)):
            for j in b[i].parameters():
                if j.requires_grad:
                        yield j

    def get_10x_lr_params(self):
        b = []
        b.append(self.layer5.parameters())
        # b.append(self.layer6.parameters())

        for j in range(len(b)):
            for i in b[j]:
                yield i

    def optim_parameters(self, args):
        if isinstance(args, float):
            lr = args
        else:
            lr = args.learning_rate
        return [{'params': self.get_1x_lr_params_NOscale(), 'lr': lr},
               {'params': self.get_10x_lr_params(), 'lr':  10*lr}]
#                {'params': self.get_10x_lr_params(), 'lr':  lr}]


class ResNetPair5_withT(ResNetPair5):
    def __init__(self, block, layers, num_classes):
        self.inplanes = 64
        super(ResNetPair5_withT, self).__init__(block, layers, num_classes)
        self.target_conv1 = nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3,
                                      bias=False)
        self.target_bn1 = nn.BatchNorm2d(64, affine=affine_par)
        for i in self.target_bn1.parameters():
            i.requires_grad = False

        self.layer1 = self._make_layer(block, 64, layers[0], first=True)
        self.target_layer1 = self._make_layer(block, 64, layers[0])
        self.layer6 = self._make_pred_layer(Classifier_Module, 2048, [6, 12, 18, 24], [6, 12, 18, 24], num_classes)
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, 0.01)

    def _make_layer(self, block=Bottleneck, planes=64, blocks=3, stride=1, dilation=1, first=False):
        model = super(ResNetPair5_withT, self)._make_layer(block, planes, blocks, stride=1, dilation=1)
        if first:
            self.inplanes = 64
        return model

    def forward(self, x, source=False):
        N, C, H, W = x.shape  # N, 3, 224, 224
        if source:
            x = self.conv1(x)  # N, 64, 112, 112
            x = self.bn1(x)
            x = self.relu(x)
            x = self.maxpool(x)  # N, 64, 57, 57
            x = self.layer1(x)  # N, 256, 57, 57
        else:
            x = self.target_conv1(x)
            x = self.target_bn1(x)
            x = self.relu(x)
            x = self.maxpool(x)
            # x = self.layer1(x)
            x = self.target_layer1(x)
        x = self.layer2(x)  # N, 512, 29, 29
        x = self.layer3(x)  # N, 1024, 29, 29
        x = self.layer4(x)  # N, 2048, 29, 29
        x1, feature = self.layer5(x)  # (N, #classes, 29, 29); (N, 76, 29, 29)
        x1 = F.interpolate(x1, (H, W), mode='bilinear', align_corners=True)  # N, #classes, 224, 224
        return x1, feature


def ResPair_Deeplab(num_classes=19, cfg=None):
    model = ResNetPair5(Bottleneck, [3, 4, 23, 3], num_classes)
    return model


if __name__ == '__main__':
    model = ResPair_Deeplab().cuda()
    img = torch.randn(2, 3, 224, 224)
    output = model(img.cuda())
    print(output.size())
