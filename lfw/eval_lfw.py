import argparse
import datetime
import os
import os.path as osp
import pytz

import torch
import torchvision
from torchvision import models
import torch.nn as nn
import torch.optim
import torch.utils.data
import torchvision.transforms as transforms
import torchvision.datasets as datasets
from torch.autograd import Variable
import torch.nn.functional as F

import yaml
import numpy as np
import sklearn.metrics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

here = osp.dirname(osp.abspath(__file__)) # output folder is located here
root_dir,_ = osp.split(here)
import sys
sys.path.append(root_dir)

import models
import utils
import data_loader



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--exp_name', default='lfw_eval_dev')
    parser.add_argument('-g', '--gpu', type=int, default=0)
    parser.add_argument('-d', '--dataset_path', 
                        default='/srv/data1/arunirc/datasets/lfw-deepfunneled')
    parser.add_argument('-p', '--pairs_path', 
                        default='./lfw/data/pairsDevTest.txt')
    parser.add_argument('--fold', type=int, default=0)
    parser.add_argument('--batch_size', type=int, default=100)

    parser.add_argument('-m', '--model_path', default=None, 
                        help='Path to pre-trained model')
    
    args = parser.parse_args()


    # CUDA setup
    os.environ['CUDA_VISIBLE_DEVICES'] = str(args.gpu)
    cuda = torch.cuda.is_available()
    torch.manual_seed(1337)
    if cuda:
        torch.cuda.manual_seed(1337)
        torch.backends.cudnn.enabled = True
        torch.backends.cudnn.benchmark = True # enable if all images are same size    



    # -----------------------------------------------------------------------------
    # 1. Dataset
    # -----------------------------------------------------------------------------
    file_ext = 'jpg' # observe, no '.' before jpg
    num_class = 8631

    pairs = read_pairs(args.pairs_path)
    path_list, issame_list = get_paths(args.dataset_path, pairs, file_ext)

    # Define data transforms
    RGB_MEAN = [ 0.485, 0.456, 0.406 ]
    RGB_STD = [ 0.229, 0.224, 0.225 ]
    test_transform = transforms.Compose([
        transforms.Scale((250,250)),  # make 250x250
        transforms.CenterCrop(150),   # then take 150x150 center crop
        transforms.Scale((224,224)),  # resized to the network's required input size
        transforms.ToTensor(),
        transforms.Normalize(mean = RGB_MEAN,
                             std = RGB_STD),
    ])

    # Create data loader
    test_loader = torch.utils.data.DataLoader(
                        data_loader.LFWDataset(
                        path_list, issame_list, test_transform), 
                    batch_size=args.batch_size, shuffle=False )


    # -----------------------------------------------------------------------------
    # 2. Model
    # -----------------------------------------------------------------------------
    model = torchvision.models.resnet50(pretrained=True)
    model.fc = torch.nn.Linear(2048, num_class)
    checkpoint = torch.load(args.model_path)        

    if checkpoint['arch'] == 'DataParallel':
        # if we trained and saved our model using DataParallel
        model = torch.nn.DataParallel(model, device_ids=[0, 1, 2, 3, 4])
        model.load_state_dict(checkpoint['model_state_dict'])
        model = model.module # get network module from inside its DataParallel wrapper
    else:
        model.load_state_dict(checkpoint['model_state_dict'])

    if cuda:
        model = model.cuda()

    # Convert the trained network into a "feature extractor"
    feature_map = list(model.children())
    feature_map.pop()  # remove the final "class prediction" layer
    extractor = nn.Sequential(*feature_map) # create feature extractor



    # -----------------------------------------------------------------------------
    # 3. Feature extraction
    # -----------------------------------------------------------------------------
    num_batches = len(test_loader) // args.batch_size
    features = []

    for batch_idx, images in enumerate(test_loader):
        print batch_idx
        x = Variable(images, volatile=True)
        if cuda:
            x = x.cuda()
        feat = extractor(x)
        if cuda:
            feat = feat.data.cpu()
        else:
            feat = feat.data
        features.append(feat)

    features = torch.stack(features)
    sz = features.size()
    features = features.view(sz[0]*sz[1], sz[2])
    features = F.normalize(features, p=2, dim=1) # L2-normalize


    # -----------------------------------------------------------------------------
    # 4. Verification
    # -----------------------------------------------------------------------------
    num_feat = features.size()[0]
    feat_pair1 = features[np.arange(0,num_feat,2),:]
    feat_pair2 = features[np.arange(1,num_feat,2),:]
    feat_dist = (feat_pair1 - feat_pair2).norm(p=2, dim=1)
    feat_dist = feat_dist.numpy()

    auc = sklearn.metrics.roc_auc_score(
            np.asarray(issame_list), -feat_dist)
    print 'AUC ROC: %.04f' % auc

    # TODO - EER

    # TODO - plot and save ROC curve



if __name__ == '__main__':
    main()

