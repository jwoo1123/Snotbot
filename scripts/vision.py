#!/usr/bin/env python
import cv2
import numpy as np
import matplotlib as plt
import math
import rospy

from std_msgs.msg import UInt8
from geometry_msgs.msg import Point

from calibrate import *

class Vision():
    def __init__(self):
        self.cap = cv2.VideoCapture(1)
        cv2.setMouseCallback('camera', self.draw_circle)

        self.img = None
        self.canny = None
        self.mode = 0

        rospy.init_node('camera')

        self.sub_mode = rospy.Subscriber('mode', UInt8, self.mode_callback)
        self.pub_fiducial = rospy.Publisher('vision', Point, queue_size=10)

        r = rospy.Rate(30)
        while not rospy.is_shutdown():
            if self.mode == 3:
                self.track_object()
            elif self.mode == 5:
                cv2.destroyAllWindows()
                self.find_squares()

            if self.img != None:
                cv2.imshow('camera', self.img)
            if self.canny != None:
                cv2.imshow('canny', self.canny)

            cv2.waitKey(1)
            r.sleep()

    def mode_callback(self, data):
        self.mode = data

    def track_object(self):
        ret, img = self.cap.read()
        roi_corners = []
        roi_selected = False

        if len(roi_corners) < 2:
            for i in roi_corners:
                cv2.circle(frame, (i[0], i[1]), 5, (0, 0, 255), -1)

        elif len(roi_corners) == 2:
            (x1, y1, x2, y2) = (roi_corners[0][0], roi_corners[0][1], roi_corners[1][0], roi_corners[1][1])
            track_window = (x1, y1, x2-x1, y2-y1)
            roi = frame[y1:y2, x1:x2]
            hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv_roi, np.array((0., 60., 30.)), np.array((180., 255., 255.)))
            roi_hist = cv2.calcHist([hsv_roi], [0], mask, [180], [0,180])
            cv2.normalize(roi_hist, roi_hist, 0, 255, cv2.NORM_MINMAX)
            term_crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 1)
            
            roi_selected = True
            roi_corners = []

        if roi_selected:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            dst = cv2.calcBackProject([hsv], [0], roi_hist, [0,180], 1)

            ret, track_window = cv2.CamShift(dst, track_window, term_crit)

            pts = cv2.cv.BoxPoints(ret)
            pts = np.int0(pts)
            cv2.polylines(frame, [pts], True, (0, 255, 255))

        self.img = frame


    def find_squares(self):
        ret, img = self.cap.read()
        img = calibrate(img)
        img_display = img
        img = cv2.inRange(img, np.array([150, 150, 150], dtype=np.uint8), np.array([255, 255, 255], dtype=np.uint8))
        img = cv2.GaussianBlur(img, (5,5), 0)
        img = cv2.morphologyEx(img, cv2.MORPH_OPEN, (9,9))
    
        squares = []
        img = cv2.Canny(img, 200, 250, apertureSize=5)
        self.canny = img
        img = cv2.dilate(img, None)
        retval, img = cv2.threshold(img, 100, 255, cv2.THRESH_BINARY)
        contours, hierarchy = cv2.findContours(img, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
        i1 = 0
        for cnt in contours:
            children = []
            children_final = []
            children_areas = 0
            average_area = 0.0

            if cv2.contourArea(cnt) > self.frame_height * self.frame_width * 0.7:
                i1 += 1
                continue

            if len(hierarchy[0]) > 0:
                i2 = hierarchy[0][i1][2]
                while i2 != -1:
                    children.append(contours[i2])
                    children_areas += cv2.contourArea(contours[i2])
                    i2 = hierarchy[0][i2][0]
            i1 += 1
    
            if len(children) > 0:
                average_area = float(children_areas) / len(children)
                for cld in children:
                    if abs(cv2.contourArea(cld) - average_area) < 100:
                        children_final.append(cld)

            cnt, cnt_square = self.is_square(cnt, 0.02) 
            if cnt_square and len(children_final) >= 5:
                squares.append(cnt)

                if len(squares) == 2:
                    if cv2.contourArea(squares[0]) > cv2.contourArea(squares[1]):
                        squares.pop(0)
                    else:
                        squares.pop(1)
    
        if len(squares) != 0:
            M = cv2.moments(np.array(squares))
            x = (int(M['m10'] / M['m00']) * 2.0 / self.frame_width) - 1.0
            y = (int(M['m01'] / M['m00']) * 2.0 / self.frame_height) - 1.0
            z = cv2.contourArea(squares[0])

            cv2.drawContours( img_display, squares, -1, (0, 255, 0), 2 )
   
            fiducial_msg = Point()
            (fiducial_msg.x, fiducial_msg.y, fiducial_msg.z) = (x, y, z)
            self.pub_fiducial.publish(fiducial_msg)
        else:
            fiducial_msg = Point()
            (fiducial_msg.x, fiducial_msg.y, fiducial_msg.z) = (0, 0, 0)
            self.pub_fiducial.publish(fiducial_msg)

        self.img = img_display

    def is_square(self, cnt, epsilon):
        cnt_len = cv2.arcLength(cnt, True)
        cnt = cv2.approxPolyDP(cnt, epsilon * cnt_len, True)

        if len(cnt) != 4 or not cv2.isContourConvex(cnt):
            return (cnt, False)
        else:
            cnt = cnt.reshape(-1, 2)
            max_cos = np.max([self.angle_cos( cnt[i], cnt[(i+1) % 4], cnt[(i+2) % 4] ) for i in xrange(4)]) 

            return (cnt, max_cos < 0.1)


    def draw_circle(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            roi_corners.append((x,y))

    def angle_cos(self, p0, p1, p2):
        d1, d2 = (p0-p1).astype('float'), (p2-p1).astype('float')
        return abs( np.dot(d1, d2) / np.sqrt( np.dot(d1, d1)*np.dot(d2, d2) ) )

if __name__ == '__main__':
    try:
        var = Vision()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
