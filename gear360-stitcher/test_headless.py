import os
import sys
import traceback
import cv2

project_dir = os.path.abspath(os.getcwd())
sys.path.insert(0, project_dir)

from src import calibration, image_pipeline, video_pipeline

output_dir = os.path.join(project_dir, 'test_output')
os.makedirs(output_dir, exist_ok=True)
cal = calibration.load_calibration()

photo_input = r'D:\DCIM\100PHOTO\360_0601.JPG'
photo_output = os.path.join(output_dir, '360_0601_360.jpg')
print('PHOTO TEST START')
try:
    image_pipeline.stitch_photo(photo_input, photo_output, cal)
    image = cv2.imread(photo_output)
    print('PHOTO OUTPUT SHAPE:', None if image is None else image.shape)
except Exception:
    print('PHOTO ERROR / TRACEBACK')
    traceback.print_exc()

video_input = r'D:\DCIM\100PHOTO\360_0597.MP4'
video_output = os.path.join(output_dir, '360_0597_360.mp4')
print('VIDEO TEST START')
try:
    result = video_pipeline.stitch_video(video_input, video_output, cal)
    print('VIDEO RETURN:', result)
    cap = cv2.VideoCapture(video_output)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    print('VIDEO INFO: frame_count={}, width={}, height={}'.format(frame_count, width, height))
except Exception:
    print('VIDEO ERROR / TRACEBACK')
    traceback.print_exc()
