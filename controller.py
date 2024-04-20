import cv2
import os
import time
import json
import numpy as np
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression
from sahi.prediction import ObjectPrediction, PredictionScore
from collections import defaultdict
import matplotlib.path as mplPath
from matplotlib.path import Path
import matplotlib.patches as patches
from ultralyticsplus import YOLO
from test import load, process

PATH_jpgs = 'RailNet_DT/rs19_val/jpgs/test'
PATH_model_seg = 'RailNet_DT/models/modelchp_85_100_0.0002865237576874738_2_0.606629.pth'
PATH_model_det = 'ultralyticsplus/yolov8s'
PATH_base = 'RailNet_DT/railway_dataset/'
eda_path = "RailNet_DT/railway_dataset/eda_table.table.json"
data_json = json.load(open(eda_path, 'r'))

def find_extreme_y_values(arr, values=[0, 6]):
        """
        Optimized function to find the lowest and highest y-values (row indices) in a 2D array where 0 or 6 appears.
        
        Parameters:
        - arr: The input 2D NumPy array.
        - values: The values to search for (default is [0, 6]).
        
        Returns:
        A tuple (lowest_y, highest_y) representing the lowest and highest y-values. If values are not found, returns None.
        """
        mask = np.isin(arr, values)
        rows_with_values = np.any(mask, axis=1)
        
        y_indices = np.nonzero(rows_with_values)[0]  # Directly finding non-zero (True) indices
        
        if y_indices.size == 0:
                return None  # Early return if values not found
        
        return y_indices[0], y_indices[-1]

def find_nearest_pairs(arr1, arr2):
        # Convert lists to numpy arrays for vectorized operations
        arr1_np = np.array(arr1)
        arr2_np = np.array(arr2)
        
        # Determine which array is shorter
        if len(arr1_np) < len(arr2_np):
                base_array, compare_array = arr1_np, arr2_np
        else:
                base_array, compare_array = arr2_np, arr1_np

        paired_base = []
        paired_compare = []

        # Mask to keep track of paired elements
        paired_mask = np.zeros(len(compare_array), dtype=bool)

        for item in base_array:
                # Calculate distances from the current item to all items in the compare_array
                distances = np.linalg.norm(compare_array - item, axis=1)
                nearest_index = np.argmin(distances)
                paired_base.append(item)
                paired_compare.append(compare_array[nearest_index])
                # Mark the paired element to exclude it from further pairing
                paired_mask[nearest_index] = True

                # Check if all elements from the compare_array have been paired
                if paired_mask.all():
                        break

        paired_base = np.array(paired_base)
        paired_compare = compare_array[paired_mask]

        return (paired_base, paired_compare) if len(arr1_np) < len(arr2_np) else (paired_compare, paired_base)

def filter_crossings(image, edges_dict):
        filtered_edges = {}
        for key, values in edges_dict.items():
                merged = [values[0]]
                for start, end in values[1:]:
                        if start - merged[-1][1] < 50:
                                
                                key_up = max([0, key-10])
                                key_down = min([1079, key+10])
                                if key_up == 0:
                                        key_up = key+20
                                if key_down == 1079:
                                        key_down = key-20
                                
                                edges_to_test_slope1 = robust_edges(image, [key_up], values=[0, 6], min_width=19)
                                edges_to_test_slope2 = robust_edges(image, [key_down], values=[0, 6], min_width=19)
                                
                                values1, edges_to_test_slope1 = find_nearest_pairs(values, edges_to_test_slope1)
                                values2, edges_to_test_slope2 = find_nearest_pairs(values, edges_to_test_slope2)
                                
                                differences_y = []
                                for i, value in enumerate(values1):
                                        if start in value:
                                                idx = list(value).index(start)
                                                differences_y.append(abs(start-edges_to_test_slope1[i][idx]))
                                        if merged[-1][1] in value:
                                                idx = list(value).index(merged[-1][1])
                                                differences_y.append(abs(merged[-1][1]-edges_to_test_slope1[i][idx]))
                                for i, value in enumerate(values2):
                                        if start in value:
                                                idx = list(value).index(start)
                                                differences_y.append(abs(start-edges_to_test_slope2[i][idx]))
                                        if merged[-1][1] in value:
                                                idx = list(value).index(merged[-1][1])
                                                differences_y.append(abs(merged[-1][1]-edges_to_test_slope2[i][idx]))
                                
                                if any(element > 30 for element in differences_y):
                                        merged[-1] = (merged[-1][0], end)
                                else:
                                        merged.append((start, end))
                        else:
                                merged.append((start, end))
                filtered_edges[key] = merged
                
        return filtered_edges

def robust_edges(image, y_levels, values=[0, 6], min_width=19):
        
        for y in y_levels:
                row = image[y, :]
                mask = np.isin(row, values).astype(int)
                padded_mask = np.pad(mask, (1, 1), 'constant', constant_values=0)
                diff = np.diff(padded_mask)
                starts = np.where(diff == 1)[0]
                ends = np.where(diff == -1)[0] - 1

                # Filter sequences based on the minimum width criteria
                filtered_edges = [(start, end) for start, end in zip(starts, ends) if end - start + 1 >= min_width]
                filtered_edges = [(start, end) for start, end in filtered_edges if 0 not in (start, end) and 1919 not in (start, end)]
        
        return filtered_edges

def find_edges(image, y_levels, values=[0, 6], min_width=19):
        """
        Find start and end positions of continuous sequences of specified values at given y-levels in a 2D array,
        filtering for sequences that meet or exceed a specified minimum width.

        Parameters:
        - arr: 2D NumPy array to search within.
        - y_levels: List of y-levels (row indices) to examine.
        - values: Values to search for (default is [0, 6]).
        - min_width: Minimum width of sequences to be included in the results.

        Returns:
        A dict with y-levels as keys and lists of (start, end) tuples for each sequence found in that row that meets the width criteria.
        """
        edges_dict = {}
        for y in y_levels:
                row = image[y, :]
                mask = np.isin(row, values).astype(int)
                padded_mask = np.pad(mask, (1, 1), 'constant', constant_values=0)
                diff = np.diff(padded_mask)
                starts = np.where(diff == 1)[0]
                ends = np.where(diff == -1)[0] - 1

                # Filter sequences based on the minimum width criteria
                filtered_edges = [(start, end) for start, end in zip(starts, ends) if end - start + 1 >= min_width]
                filtered_edges = [(start, end) for start, end in filtered_edges if 0 not in (start, end) and 1919 not in (start, end)]
                
                edges_with_guard_rails = []
                for edge in filtered_edges:
                        cutout_left = image[y,edge[0]-50:edge[0]][::-1]
                        cutout_right = image[y,edge[1]:edge[1]+50]
                        
                        not_ones = np.where(cutout_left != 1)[0]
                        if len(not_ones) > 0 and not_ones[0] > 0:
                                last_one_index = not_ones[0] - 1
                                edge = (edge[0] - last_one_index,) + edge[1:]
                        else:
                                last_one_index = None if len(not_ones) == 0 else not_ones[-1] - 1
                        
                        not_ones = np.where(cutout_right != 1)[0]
                        if len(not_ones) > 0 and not_ones[0] > 0:
                                last_one_index = not_ones[0] - 1
                                edge = (edge[0], edge[1] - last_one_index) + edge[2:]
                        else:
                                last_one_index = None if len(not_ones) == 0 else not_ones[-1] - 1
                        
                        edges_with_guard_rails.append(edge)

                edges_dict[y] = edges_with_guard_rails
        
        edges_dict = {k: v for k, v in edges_dict.items() if v}
        
        edges_dict = filter_crossings(image, edges_dict)
        
        return edges_dict

def find_rails(arr, y_levels, values=[9, 10], min_width=5):
        edges_all = []
        for y in y_levels:
                row = arr[y, :]
                mask = np.isin(row, values).astype(int)
                padded_mask = np.pad(mask, (1, 1), 'constant', constant_values=0)
                diff = np.diff(padded_mask)
                starts = np.where(diff == 1)[0]
                ends = np.where(diff == -1)[0] - 1

                # Filter sequences based on the minimum width criteria
                filtered_edges = [(start, end) for start, end in zip(starts, ends) if end - start + 1 >= min_width]
                filtered_edges = [(start, end) for start, end in filtered_edges if 0 not in (start, end) and 1919 not in (start, end)]
                edges_all = filtered_edges
        
        return edges_all

def mark_edges(arr, edges_dict, mark_value=30):
        """
        Marks a 5x5 zone around the edges found in the array with a specific value.

        Parameters:
        - arr: The original 2D NumPy array.
        - edges_dict: A dictionary with y-levels as keys and lists of (start, end) tuples for edges.
        - mark_value: The value used to mark the edges.

        Returns:
        The modified array with marked zones.
        """
        marked_arr = np.copy(arr)  # Create a copy of the array to avoid modifying the original
        offset = 2  # To mark a 5x5 area, we go 2 pixels in each direction from the center

        for y, edges in edges_dict.items():
                for start, end in edges:
                        # Mark a 5x5 zone around the start and end positions
                        for dy in range(-offset, offset + 1):
                                for dx in range(-offset, offset + 1):
                                        # Check array bounds before marking
                                        if 0 <= y + dy < marked_arr.shape[0] and 0 <= start + dx < marked_arr.shape[1]:
                                                marked_arr[y + dy, start + dx] = mark_value
                                        if 0 <= y + dy < marked_arr.shape[0] and 0 <= end + dx < marked_arr.shape[1]:
                                                marked_arr[y + dy, end + dx] = mark_value

        return marked_arr

def find_rail_sides(img, edges_dict):
        left_border = []
        right_border = []
        for y,xs in edges_dict.items():
                rails = find_rails(img, [y], values=[9,10], min_width=5)
                left_border_actual = [min(xs)[0],y]
                right_border_actual = [max(xs)[1],y]
                
                for zone in rails:
                        if abs(zone[1]-left_border_actual[0]) < y*0.04: # dynamic treshold
                                left_border_actual[0] = zone[0]
                        if abs(zone[0]-right_border_actual[0]) < y*0.04:
                                right_border_actual[0] = zone[1]
                
                left_border.append(left_border_actual)
                right_border.append(right_border_actual)

        # removing detected uncontioussness
        left_border, flags_l, _ = robust_rail_sides(left_border) # filter outliers
        right_border, flags_r, _ = robust_rail_sides(right_border)
        
        return left_border, right_border, flags_l, flags_r

def robust_rail_sides(border, threshold=7):
        border = np.array(border)
        
        # delete borders found on the bottom side of the image
        border = border[border[:, 1] != 1079]
        
        
        steps_x = np.diff(border[:, 0])
        median_step = np.median(np.abs(steps_x))
        
        threshold_step = np.abs(threshold*np.abs(median_step))
        treshold_overcommings = abs(steps_x) > abs(threshold_step)
        
        flags = []
        
        if True not in treshold_overcommings:
                return border, flags, []
        else:
                overcommings_indices = [i for i, element in enumerate(treshold_overcommings) if element == True]
                if overcommings_indices and np.all(np.diff(overcommings_indices) == 1):
                        overcommings_indices = [overcommings_indices[0]]
                
                filtered_border = border
                
                previously_deleted = []
                for i in overcommings_indices:
                        for item in previously_deleted:
                                if item[0] < i:
                                        i -= item[1]
                        first_part = filtered_border[:i+1]
                        second_part = filtered_border[i+1:]
                        if len(second_part)<2:
                                filtered_border = first_part
                                previously_deleted.append([i,len(second_part)])
                        elif len(first_part)<2:
                                filtered_border = second_part
                                previously_deleted.append([i,len(first_part)])
                        else:
                                first_b, _, deleted_first = robust_rail_sides(first_part)
                                second_b, _, _ = robust_rail_sides(second_part)
                                filtered_border = np.concatenate((first_b,second_b), axis=0)
                                
                                if deleted_first:
                                        for deleted_item in deleted_first:
                                                if deleted_item[0]<=i:
                                                        i -= deleted_item[1]
                                        
                                flags.append(i)
                
                return filtered_border, flags, previously_deleted

def find_dist_from_edges(image, edges_dict, left_border, right_border, real_life_width_mm, real_life_target_mm, mark_value=30):
        """
        Mark regions representing a real-life distance (e.g., 2 meters) to the left and right from the furthest edges.
        
        Parameters:
        - arr: 2D NumPy array representing the image.
        - edges_dict: Dictionary with y-levels as keys and lists of (start, end) tuples for edges.
        - real_life_width_mm: The real-world width in millimeters that the average sequence width represents.
        - real_life_target_mm: The real-world distance in millimeters to mark from the edges.
        
        Returns:
        - A NumPy array with the marked regions.
        """
        # Calculate the rail widths
        diffs_widths = {k: sum(e-s for s, e in v) / len(v) for k, v in edges_dict.items() if v}
        diffs_width = {k: max(e-s for s, e in v) for k, v in edges_dict.items() if v}

        # Pixel to mm scale factor
        scale_factors = {k: real_life_width_mm / v for k, v in diffs_width.items()}
        # Converting the real-life target distance to pixels
        target_distances_px = {k: int(real_life_target_mm / v) for k, v in scale_factors.items()}

        mark=1
        
        # Mark the regions representing the target distance to the left and right from the furthest edges
        end_points_left = {}
        for point in left_border:
                min_edge = point[0]
                
                # Ensure we stay within the image bounds
                #left_mark_start = max(0, min_edge - int(target_distances_px[point[1]]))
                left_mark_start = min_edge - int(target_distances_px[point[1]])
                end_points_left[point[1]] = left_mark_start
                
                if mark:
                        # Mark the left region
                        if left_mark_start < min_edge:
                                image[point[1], left_mark_start:min_edge] = mark_value
        
        end_points_right = {}
        for point in right_border:
                max_edge = point[0]
                
                # Ensure we stay within the image bounds
                right_mark_end = min(image.shape[1], max_edge + int(target_distances_px[point[1]]))
                if right_mark_end != image.shape[1]:
                        end_points_right[point[1]] = right_mark_end
                
                if mark:
                        # Mark the right region
                        if max_edge < right_mark_end:
                                image[point[1], max_edge:right_mark_end] = mark_value

        return image, end_points_left, end_points_right

def bresenham_line(x0, y0, x1, y1):
        """
        Generate the coordinates of a line from (x0, y0) to (x1, y1) using Bresenham's algorithm.
        """
        line = []
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy  # error value e_xy

        while True:
                line.append((x0, y0))  # Add the current point to the line
                if x0 == x1 and y0 == y1:
                        break
                e2 = 2 * err
                if e2 >= dy:  # e_xy+e_x > 0
                        err += dy
                        x0 += sx
                if e2 <= dx:  # e_xy+e_y < 0
                        err += dx
                        y0 += sy

        return line

def interpolate_end_points(end_points_dict, flags):
        line_arr = []
        ys = list(end_points_dict.keys())
        xs = list(end_points_dict.values())
        
        if flags and len(flags) == 1:
                pass
        elif flags and np.all(np.diff(flags) == 1):
                flags = [flags[0]]
        
        for i in range(0, len(ys) - 1):
                if i in flags:
                        continue
                y1, y2 = ys[i], ys[i + 1]
                x1, x2 = xs[i], xs[i + 1]
                line = np.array(bresenham_line(x1, y1, x2, y2))
                if np.any(line[:, 0] < 0):
                        line = line[line[:, 0] > 0]
                line_arr = line_arr + list(line)
        
        if line_arr == []:
                print("line_arr was empty when interpolating")
        
        return line_arr

def extrapolate_line(pixels, image, min_y=None, extr_pixels=10):
        """
        Extrapolate a line based on the last segment using linear regression.
        
        Parameters:
        - pixels: List of (x, y) tuples representing line pixel coordinates.
        - image: 2D numpy array representing the image.
        - min_y: Minimum y-value to extrapolate to (optional).
        
        Returns:
        - A list of new extrapolated (x, y) pixel coordinates.
        """
        if len(pixels) < extr_pixels:
                print("Not enough pixels to perform extrapolation.")
                return []

        recent_pixels = np.array(pixels[-extr_pixels:])
        
        X = recent_pixels[:, 0].reshape(-1, 1)  # Reshape for sklearn
        y = recent_pixels[:, 1]
        
        model = LinearRegression()
        model.fit(X, y)
        
        slope = model.coef_[0]
        intercept = model.intercept_

        extrapolate = lambda x: slope * x + intercept
        
        # Calculate direction based on last two pixels
        dx, dy = 0, 0  # Default values
        
        x_diffs = []
        y_diffs = []
        for i in range(1,extr_pixels-1):
                x_diffs.append(pixels[-i][0] - pixels[-(i+1)][0])
                y_diffs.append(pixels[-i][1] - pixels[-(i+1)][1])
                
        x_diff = x_diffs[np.argmax(np.abs(x_diffs))]
        y_diff = y_diffs[np.argmax(np.abs(y_diffs))]
        
        if abs(int(x_diff)) >= abs(int(y_diff)):
                dx = 1 if x_diff >= 0 else -1
        else:
                dy = 1 if y_diff >= 0 else -1

        last_pixel = pixels[-1]
        new_pixels = []
        x, y = last_pixel

        min_y = min_y if min_y is not None else image.shape[0] - 1
        
        while 0 <= x < image.shape[1] and min_y <= y < image.shape[0]:
                if dx != 0:  # Horizontal or diagonal movement
                        x += dx
                        y = int(extrapolate(x))
                elif dy != 0:  # Vertical movement
                        y += dy
                        # For vertical lines, approximate x based on the last known value
                        x = int(x)
                        
                if 0 <= y < image.shape[0] and 0 <= x < image.shape[1]:
                        new_pixels.append((x, y))
                else:
                        break

        return new_pixels

def extrapolate_borders(dist_marked_id_map, border_l, border_r, lowest_y):
        
        #border_extrapolation_l1 = extrapolate_line(border_l, dist_marked_id_map, lowest_y)
        border_extrapolation_l2 = extrapolate_line(border_l[::-1], dist_marked_id_map, lowest_y)
        
        #border_extrapolation_r1 = extrapolate_line(border_r, dist_marked_id_map, lowest_y)
        border_extrapolation_r2 = extrapolate_line(border_r[::-1], dist_marked_id_map, lowest_y)
        
        #border_l = border_extrapolation_l2[::-1] + border_l + border_extrapolation_l1
        #border_r = border_extrapolation_r2[::-1] + border_r + border_extrapolation_r1
        
        border_l = border_extrapolation_l2[::-1] + border_l
        border_r = border_extrapolation_r2[::-1] + border_r
        
        return border_l, border_r

def find_zone_border(image, edges, irl_width_mm=1435, irl_target_mm=1000, lowest_y = 0):
        
        left_border, right_border, flags_l, flags_r = find_rail_sides(image, edges)
        
        dist_marked_id_map, end_points_left, end_points_right = find_dist_from_edges(image, edges, left_border, right_border, irl_width_mm, irl_target_mm)
        
        border_l = interpolate_end_points(end_points_left, flags_l)
        border_r = interpolate_end_points(end_points_right, flags_r)
        
        border_l, border_r = extrapolate_borders(dist_marked_id_map, border_l, border_r, lowest_y)
        
        return [border_l, border_r]

def get_clues(segmentation_mask, number_of_clues):
        
        lowest, highest = find_extreme_y_values(segmentation_mask)
        clue_step = int((highest - lowest) / number_of_clues+1)
        clues = []
        for i in range(number_of_clues):
                clues.append(highest - (i*clue_step))
        clues.append(lowest+int(0.5*clue_step))
                
        return clues

def border_handler(id_map, edges, target_distances):
        
        lowest, _ = find_extreme_y_values(id_map)
        borders = []
        for target in target_distances:
                borders.append(find_zone_border(id_map, edges, irl_target_mm=target, lowest_y = lowest))
                for border in borders:
                        for point in border[0]:
                                id_map[point[1],point[0]] = 30
                        for point in border[1]:
                                id_map[point[1],point[0]] = 30
                
        return borders, id_map

def segment(image_size, filename, PATH_jpgs, PATH_model, dataset_type, item=None):
        image_norm, _, mask, _, model = load(filename, PATH_jpgs, PATH_model, image_size, dataset_type=dataset_type, item=item)
        id_map = process(model, image_norm, mask, model_type)
        id_map = cv2.resize(id_map, [1920,1080], interpolation=cv2.INTER_NEAREST)
        return id_map

def detect(PATH_model, filename_img, PATH_jpgs):
        
        model = YOLO(PATH_model)

        model.overrides['conf'] = 0.25  # NMS confidence threshold
        model.overrides['iou'] = 0.45  # NMS IoU threshold
        model.overrides['agnostic_nms'] = False  # NMS class-agnostic
        model.overrides['max_det'] = 1000  # maximum number of detections per image
        
        image = cv2.imread(os.path.join(PATH_jpgs, filename_img))
        results = model.predict(image)

        return results, model, image

def manage_detections(results, model):
        names = model.model.names
        bbox = results[0].boxes.xywh.tolist()
        cls = results[0].boxes.cls.tolist()
        accepted_stationary = np.array([24,25,26,28,29,30,31,36,56,57,59,60,61,62,63,68,69,70,71,72,78])
        accepted_moving = np.array([0,1,2,3,5,7,15,16,17,18,19,20,21,22,23])
        boxes_moving = {}
        boxes_stationary = {}
        if len(bbox) > 0:
                for xywh, clss in zip(bbox, cls):
                        if clss in accepted_moving:
                                if clss in boxes_moving.keys() and len(boxes_moving[clss]) > 0:
                                        boxes_moving[clss].append(xywh)
                                else:
                                        boxes_moving[clss] = [xywh]
                        if clss in accepted_stationary:
                                if clss in boxes_stationary.keys() and len(boxes_stationary[clss]) > 0:
                                        boxes_stationary[clss].append(xywh)
                                else:
                                        boxes_stationary[clss] = [xywh]

        return boxes_moving, boxes_stationary

def compute_detection_borders(borders, output_dims=[1080,1920]):
        det_height = output_dims[0]-1
        det_width = output_dims[1]-1
        
        for i,border in enumerate(borders):
                border_l = np.array(border[0])
                
                if list(border_l):
                        pass
                else:
                        border_l=np.array([[0,0],[0,0]])
                
                endpoints_l = [border_l[0],border_l[-1]]
                
                border_r = np.array(border[1])
                if list(border_r):
                        pass
                else:
                        border_r=np.array([[0,0],[0,0]])
                        
                endpoints_r = [border_r[0],border_r[-1]]
                
                interpolated_top = bresenham_line(endpoints_l[1][0],endpoints_l[1][1],endpoints_r[1][0],endpoints_r[1][1])

                if (endpoints_l[0][0] == 0 and endpoints_r[0][1] == det_height) or (endpoints_l[0][0] == 0 and endpoints_r[0][1] == det_height-1):
                        y_values = np.arange(endpoints_l[0][1], det_height)
                        x_values = np.full_like(y_values, 0)
                        bottom1 = np.column_stack((x_values, y_values))
                        
                        x_values = np.arange(0, endpoints_r[0][0])
                        y_values = np.full_like(x_values, det_height)
                        bottom2 = np.column_stack((x_values, y_values))
                        
                        interpolated_bottom = np.vstack((bottom1, bottom2))
                        
                elif (endpoints_l[0][1] == det_height and endpoints_r[0][0] == det_width) or (endpoints_l[0][1] == det_height-1 and endpoints_r[0][0] == det_width):
                        y_values = np.arange(endpoints_r[0][1], det_height)
                        x_values = np.full_like(y_values, det_width)
                        bottom1 = np.column_stack((x_values, y_values))
                        
                        x_values = np.arange(endpoints_l[0][0], det_width)
                        y_values = np.full_like(x_values, det_height)
                        bottom2 = np.column_stack((x_values, y_values))
                        
                        interpolated_bottom = np.vstack((bottom1, bottom2))
                        
                elif endpoints_l[0][0] == 0 and endpoints_r[0][0] == det_width:
                        y_values = np.arange(endpoints_l[0][1], det_height)
                        x_values = np.full_like(y_values, 0)
                        bottom1 = np.column_stack((x_values, y_values))
                        
                        y_values = np.arange(endpoints_r[0][1], det_height)
                        x_values = np.full_like(y_values, det_width)
                        bottom2 = np.column_stack((x_values, y_values))
                        
                        bottom3_mid = bresenham_line(bottom1[-1][0],bottom1[-1][1],bottom2[-1][0],bottom2[-1][1])
                        
                        interpolated_bottom = np.vstack((bottom1, bottom2, bottom3_mid))

                        
                else:
                        interpolated_bottom = bresenham_line(endpoints_l[0][0],endpoints_l[0][1],endpoints_r[0][0],endpoints_r[0][1])
                
                borders[i].append(interpolated_bottom)
                borders[i].append(interpolated_top)
                
        return borders

def classify_detections(boxes_moving, boxes_stationary, borders, img_dims, output_dims=[1080,1920]):
        img_h, img_w, _ = img_dims
        img_h_scaletofullHD = output_dims[1]/img_w
        img_w_scaletofullHD = output_dims[0]/img_h
        colors = ["yellow","orange","red","green","blue"]
        
        borders = compute_detection_borders(borders,output_dims)
        
        boxes_info = []
        #boxes_moving[0.0].append([250,1000,20,40])
        
        if boxes_moving or boxes_stationary:
                if boxes_moving:
                        for item, coords in boxes_moving.items():
                                for coord in coords:
                                        x = coord[0]*img_w_scaletofullHD
                                        y = coord[1]*img_h_scaletofullHD
                                        w = coord[2]*img_w_scaletofullHD
                                        h = coord[3]*img_h_scaletofullHD
                                        
                                        complete_border = []
                                        criticality = -1
                                        color = None
                                        for i,border in enumerate(reversed(borders)):
                                                complete_border = np.vstack((border[0], border[1], border[2], border[3]))
                                                
                                                instance_border_path = mplPath.Path(np.array(complete_border))
                                                is_inside_borders = instance_border_path.contains_point((x,y))
                                                
                                                if is_inside_borders:
                                                        criticality = i
                                                        color = colors[i]
                                                        
                                        if criticality == -1:
                                                color = colors[3]
                                                
                                        boxes_info.append([item, criticality, color, [x, y],1])
                                                
                if boxes_stationary:
                        for item, coords in boxes_stationary.items():
                                for coord in coords:
                                        x = coord[0]*img_w_scaletofullHD
                                        y = coord[1]*img_h_scaletofullHD
                                        w = coord[2]*img_w_scaletofullHD
                                        h = coord[3]*img_h_scaletofullHD
                                        
                                        complete_border = []
                                        criticality = -1
                                        color = None
                                        is_inside_borders = 0
                                        for i,border in enumerate(reversed(borders), start=len(borders) - 1):
                                                complete_border = np.vstack((border[0], border[1], border[2], border[3]))
                                                instance_border_path = mplPath.Path(np.array(complete_border))
                                                is_inside_borders = instance_border_path.contains_point((x,y))
                                                
                                                if is_inside_borders:
                                                        criticality = i
                                                        color = colors[4]
                                                
                                        if criticality == -1:
                                                color = colors[3]
                                                
                                        boxes_info.append([item, criticality, color, [x, y],0])
        
                return boxes_info
        
        else:
                print("No accepted detections in this image.")
                return []

def draw_classification(classification, id_map):
        
        if classification:
                for box in classification:
                        x,y = box[3]
                        mark_value = 30
                        
                        x_start = int(max(x - 2, 0))
                        x_end = int(min(x + 3, id_map.shape[1]))
                        y_start = int(max(y - 2, 0))
                        y_end = int(min(y + 3, id_map.shape[0]))
                        
                        id_map[y_start:y_end, x_start:x_end] = mark_value
        else:
                return

def show_result(classification, id_map, names):
        if classification:
                plt.imshow(id_map)
                for box in classification:
                        x,y = box[3]
                        name = names[box[0]]
                        color = box[2]
                        plt.text(x, y+10, name, color=color, fontsize=10, ha='center', va='center')

                plt.show()
        else:
                return

def run(image_size, filepath_img, PATH_jpgs, PATH_model_seg, PATH_model_det, dataset_type, target_distances, vis, item=None, num_ys = 15):

        segmentation_mask = segment(image_size, filepath_img, PATH_jpgs, PATH_model_seg, dataset_type, item)
        print('File: {}'.format(filepath_img))
        
        output_size = segmentation_mask.shape
        
        # Border search
        clues = get_clues(segmentation_mask, num_ys)
        #edges = find_edges(segmentation_mask, clues, min_width=int(segmentation_mask.shape[1]*0.02))
        edges = find_edges(segmentation_mask, clues, min_width=0)
        #id_map_marked = mark_edges(segmentation_mask, edges)
        
        borders, id_map = border_handler(segmentation_mask, edges, target_distances)
        
        # Detection
        results, model, image = detect(PATH_model_det, filepath_img, PATH_jpgs)
        boxes_moving, boxes_stationary = manage_detections(results, model)
        
        classification = classify_detections(boxes_moving, boxes_stationary, borders, image.shape, output_dims=output_size)
        
        draw_classification(classification, id_map)
        if classification:
                show_result(classification, id_map, model.names)
        else:
                if vis:
                        plt.imshow(segmentation_mask)
                        plt.title('Image with no objects detected')
                        plt.show()

if __name__ == "__main__":

        dataset_type = 'railsem19' #railsem19 or pilsen
        vis = True
        image_size = [1024,1024]
        model_type = "segformer" #segformer or deeplab
        target_distances = [5400,6500,8000]
        num_ys = 10
        
        if dataset_type == 'pilsen':
                for item in enumerate(data_json["data"]):
                        filepath_img = item[1][1]["path"]
                        #filepath_img = 'media/images/44aabd7ea3e4a32e034f/frame_132280.png'
                        # segmentace - frame_121440.png,frame_121560.png,frame_123320.png,frame_125400.png,frame_127000.png,frame_128040.png
                        run(image_size, filepath_img, PATH_base, PATH_model_seg, PATH_model_det, dataset_type, target_distances, vis=vis, item=item, num_ys=num_ys)
        else:
                for filename_img in os.listdir(PATH_jpgs):
                        #filename_img = "rs07898.jpg" #rs07659 55 rs07718.jpg rs07662.jpg - rs07898.jpg (priklad s lidmi pro 5400,6500,8000)
                        run(image_size, filename_img, PATH_jpgs, PATH_model_seg, PATH_model_det, dataset_type, target_distances, vis=vis, item=None, num_ys=num_ys)
