from pathlib import Path
from torchvision.datasets.vision import VisionDataset
from albumentations.pytorch import ToTensorV2
import albumentations as A
import numpy as np
import torch
import cv2
import re
import os


class CustomDataset(VisionDataset):
    def __init__(self, image_folder, mask_folder, image_size, subset, val_fraction=0.1):
        self.image_folder = Path(image_folder)
        self.mask_folder = Path(mask_folder)
        self.val_fraction = val_fraction
        
        # Define data transformations using Albumentations
        if subset == 'Train': 
            self.transform_base = A.Compose([
                            A.Resize(height=image_size[0], width=image_size[1], interpolation=cv2.INTER_NEAREST),
                            A.HorizontalFlip(p=0.5),
                            A.RandomBrightnessContrast(p=0.3),
                            A.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.2, p=0.3),
                            A.ShiftScaleRotate(shift_limit=0.0625, scale_limit=0.1, rotate_limit=15, p=0.5),
                            A.RandomResizedCrop(height=image_size[0], width=image_size[1], scale=(0.8, 1.0)),
                            A.CoarseDropout(max_holes=8, max_height=8, max_width=8, min_holes=2, fill_value=0, p=0.5),
                            A.GaussianBlur(blur_limit=(3, 7), p=0.2),
                            ])
        elif subset == 'Valid':
            self.transform_base = A.Compose([
                            A.Resize(height=image_size[0], width=image_size[1], interpolation=cv2.INTER_NEAREST),
                            ])
        
        self.transform_img = A.Compose([
                            A.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225], max_pixel_value=255.0, p=1.0),
                            ToTensorV2(p=1.0),
                            ])
        self.transform_mask = A.Compose([
                            ToTensorV2(p=1.0),
                            ])
        # all files
        self.image_list = np.array(sorted(Path(self.image_folder).glob("*")))
        self.mask_list = np.array(sorted(Path(self.mask_folder).glob("*")))

        for file_path in self.image_list:
            if 'desktop.ini' in file_path.name:
                file_path.unlink()
        for file_path in self.mask_list:
            if 'desktop.ini' in file_path.name:
                file_path.unlink()

        self.mask_list = np.array(sorted(self.mask_list, key=lambda path: int(re.findall(r'\d+', path.stem)[0]) if re.findall(r'\d+', path.stem) else 0))

        if subset == 'Train':  # split dataset to 1-fraction of train data, default fraction == 0.1
            self.image_names = self.image_list[:int(np.ceil(len(self.image_list) * (1 - self.val_fraction)))]
            self.mask_names = self.mask_list[:int(np.ceil(len(self.mask_list) * (1 - self.val_fraction)))]
        elif subset == 'Valid':  # val data - data of length fraction
            self.image_names = self.image_list[int(np.ceil(len(self.image_list) * (1 - self.val_fraction))):]
            self.mask_names = self.mask_list[int(np.ceil(len(self.mask_list) * (1 - self.val_fraction))):]
        else:
            print('Invalid data subset.')

    def __len__(self) -> int:
        return len(self.image_names)

    def __getitem__(self, idx):
        image_path = self.image_names[idx]
        mask_path = self.mask_names[idx]

        with open(image_path, "rb") as image_file, open(mask_path, "rb") as mask_file:

            image = cv2.imread(image_file.name)
            mask = cv2.imread(mask_file.name, cv2.IMREAD_GRAYSCALE)
        
            transformed = self.transform_base(image=image, mask=mask)
            transformed_image = transformed['image']
            transformed_mask = transformed['mask']
            
            image = self.transform_img(image=transformed_image)['image']
            mask = self.transform_mask(image=transformed_mask)['image']

            # ignore not well segmented classes
            ignore = True
            if ignore:
                ignore_list = [0,1,2,6,8,9,15,16,19,20]
                for cls in ignore_list:
                    mask[mask==cls] = 255

                ignore_set = set(ignore_list)
                cls_remaining = [num for num in range(0, 22) if num not in ignore_set]

                # renumber the remaining classes 0-number of remaining classes
                for idx, cls in enumerate(cls_remaining):
                    mask[mask==cls] = idx

                mask[mask==255] = 12 # background
            
            ploting = False
            if ploting:
                import matplotlib.pyplot as plt
                mask[mask == 255] = 0

                plt.figure()
                plt.subplot(1, 2, 1)
                plt.imshow(mask.squeeze(), cmap='gray')

                plt.subplot(1, 2, 2) 
                plt.imshow(image[0], cmap='gray')
                plt.show()

            sample = [image, mask.squeeze().long()]
            return sample