# MIT License
#
# Copyright (c) 2022 Kristian Ollikainen
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import math
# This script takes screenshots of the screen and creates a timelapse pictures from them.
import pathlib
import datetime
import threading
import subprocess
import time

import imageio.v3 as iio
import screeninfo
from mss import mss
import tkinter as tk
from PIL import Image
from static_ffmpeg import run
from pynput.mouse import Controller

VERSION = "0.1.4"


class ScreenTimelapseApp(tk.Frame):
	def __init__(self, master=None):
		super().__init__(master)
		self.master = master
		self.pack()

		self.quit = None
		self.region = None
		self.startstop = None
		self.stop = None
		self.title = None
		self.spfText = None
		self.capSPF = None
		self.outputFPS = None
		self.outFPSText = None
		self.capturedFrames = None
		self.regionData = {"top": 0, "left": 0, "width": 0, "height": 0}
		self.captureThread = None
		self.stopEvent = threading.Event()
		self.directory = None
		self.camMode = None
		self.useCamera = False
		self.cameraSelector = None

		self.create_widgets()

	def set_cammode(self):
		self.useCamera = not self.useCamera
		if self.useCamera:
			self.cameraSelector["state"] = "normal"
		else:
			self.cameraSelector["state"] = "disabled"

	def create_widgets(self):
		self.title = tk.Label(self, text=f"py-screen-timelapse v{VERSION}")
		self.title.pack(side="top")

		self.camMode = tk.Checkbutton(self, text="Use camera instead", onvalue=True, offvalue=False, command=self.set_cammode)
		self.camMode.pack(side="top")

		self.cameraSelector = tk.Entry(self)
		self.cameraSelector.insert(0, "1")
		self.cameraSelector.pack(side="top")
		self.cameraSelector["state"] = "disabled"

		self.region = tk.Button(self, text="Region", command=self.set_region)
		self.region.pack(side="top")

		self.startstop = tk.Button(self, text="Start", command=self.do_start)
		self.startstop["fg"] = "green"

		# Disable startstop button until region is set
		#self.startstop["state"] = "disabled"
		self.startstop.pack(side="top")

		self.spfText = tk.Label(self, text="Capture every n seconds:")
		self.spfText.pack(side="top")

		self.capSPF = tk.Entry(self)
		self.capSPF.insert(0, "1")	# Seconds per frame
		self.capSPF.pack(side="top")

		self.outFPSText = tk.Label(self, text="Output FPS:")
		self.outFPSText.pack(side="top")

		self.outputFPS = tk.Entry(self)
		self.outputFPS.insert(0, "60")	# Output FPS
		self.outputFPS.pack(side="top")

		self.capturedFrames = tk.Label(self, text="Captured frames: 0")
		self.capturedFrames.pack(side="bottom")

		self.quit = tk.Button(self, text="Quit", fg="red", command=self.on_quit)
		self.quit.pack(side="bottom")

	def get_dpi(self, curPos):
		# Find monitor that has curPos
		for monitor in screeninfo.get_monitors():
			if monitor.x <= curPos[0] <= monitor.x + monitor.width and monitor.y <= curPos[1] <= monitor.y + monitor.height:
				widthInches = monitor.width_mm / 25.4
				heightInches = monitor.height_mm / 25.4
				return (math.hypot(monitor.width, monitor.height) / math.hypot(widthInches, heightInches)) / 1.5

	def set_region(self):
		# Specify region by clicking and dragging a rectangle on monitor (create undecorated window)
		x1, y1 = 0, 0
		left, top, right, bottom = 0, 0, 0, 0
		screenDPI = 0
		resizing = False
		text = None
		mouse = Controller()

		# Get DPI of current screen
		screenDPI = self.get_dpi((left, top))

		def on_click(event):
			nonlocal x1, y1
			if not resizing:
				x1, y1 = event.x, event.y

		def on_move(event):
			nonlocal x1, y1, resizing, left, top, right, bottom, screenDPI

			# If not resizing, get mouse position to reposition fakeRoot
			if not resizing:
				mX, mY = mouse.position
				fakeRoot.geometry(f"+{mX - x1}+{mY - y1}")
				left = mX - x1
				top = mY - y1
				screenDPI = self.get_dpi((left, top))
			else:
				# Otherwise, resize fakeRoot, minimum is 200x200
				mX, mY = mouse.position
				width = max(200, mX - left)
				height = max(200, mY - top)
				fakeRoot.geometry(f"{width}x{height}+{left}+{top}")
				right = left + width
				bottom = top + height

		def finish():
			nonlocal x1, y1, left, top, right, bottom, screenDPI
			# Save region data
			self.regionData["left"] = left
			self.regionData["top"] = top

			# Handle DPI scaling
			w = (right - left) * (screenDPI / 96.0)
			h = (bottom - top) * (screenDPI / 96.0)

			# Width and height must be divisible by
			self.regionData["width"] = int(w - w % 2)
			self.regionData["height"] = int(h - h % 2)

			print(f"Region set to {self.regionData}")

			# Enable startstop button
			self.startstop["state"] = "normal"

			fakeRoot.destroy()

		def toggle_resize_move():
			nonlocal resizing, text
			resizing = not resizing
			if resizing:
				text["text"] = "RESIZING"
			else:
				text["text"] = "MOVING"

		fakeRoot = tk.Tk()
		fakeRoot.overrideredirect(True)
		fakeRoot.attributes("-topmost", True)
		fakeRoot.attributes("-alpha", 0.75)
		fakeRoot.bind("<Button-1>", on_click)
		fakeRoot.bind("<B1-Motion>", on_move)
		# Set width and height to 100x100 to prevent being too small
		fakeRoot.geometry("200x200+0+0")

		# Move to screen center
		screenWidth = fakeRoot.winfo_screenwidth()
		screenHeight = fakeRoot.winfo_screenheight()

		x1 = (screenWidth // 2) - 100
		y1 = (screenHeight // 2) - 100
		left = x1
		top = y1
		fakeRoot.geometry(f"+{left}+{top}")

		# Add text at center
		text = tk.Label(fakeRoot, text="MOVING")
		text.pack()
		text.place(relx=0.5, rely=0.5, anchor="center")

		# Add button to cancel and switch between resize and move
		cancel = tk.Button(fakeRoot, text="Cancel", command=fakeRoot.destroy)
		cancel.pack()

		resizeMoveToggle = tk.Button(fakeRoot, text="Move/Resize", command=toggle_resize_move)
		resizeMoveToggle.pack()

		finishButton = tk.Button(fakeRoot, text="Finish", command=finish)
		finishButton.pack()

		fakeRoot.mainloop()

	def do_start(self):
		if not self.useCamera and (self.regionData["width"] == 0 or self.regionData["height"] == 0
								   or self.regionData["left"] == 0 or self.regionData["top"] == 0):
			return

		# If invalid inputs for seconds per frame or output FPS, return
		targetSPF, targetCam = 0, 1
		try:
			targetSPF = float(self.capSPF.get())
			targetCam = int(self.cameraSelector.get())
		except ValueError:
			return

		# Change startstop button to stop
		self.startstop["text"] = "Stop"
		self.startstop["command"] = self.do_stop
		self.startstop["fg"] = "red"

		# Disable region button
		self.region["state"] = "disabled"

		# Disable spf and fps entries
		self.capSPF["state"] = "disabled"
		self.outputFPS["state"] = "disabled"
		self.cameraSelector["state"] = "disabled"
		self.camMode["state"] = "disabled"

		# Create new directory with current date under "./timelapses/" and start capturing
		self.directory = pathlib.Path("timelapses") / datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
		self.directory.mkdir(parents=True, exist_ok=True)

		def capture_loop():
			frame = 0
			if not self.useCamera:
				with mss() as sct:
					while not self.stopEvent.is_set():
						sct_img = sct.grab(self.regionData)

						# Convert to PIL Image
						img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

						# Save image (number of frame as filename, padded with 6 zeros)
						img.save(self.directory / f"{frame:06d}.png")
						frame += 1

						# Update capturedFrames label
						self.capturedFrames["text"] = f"Captured frames: {frame}"

						# Sleep for specified seconds per frame
						time.sleep(targetSPF)
			else:
				for f in iio.imiter(f"<video{targetCam}>"):
					if self.stopEvent.is_set():
						return

					img = Image.fromarray(f)

					img.save(self.directory / f"{frame:06d}.png")
					frame += 1

					self.capturedFrames["text"] = f"Captured frames: {frame}"

					time.sleep(targetSPF)

		# Create capture thread
		self.captureThread = threading.Thread(target=capture_loop, daemon=True)
		print("Starting capture thread")
		self.stopEvent.clear()
		self.captureThread.start()

	def do_stop(self):
		# Stop capturing
		self.stopEvent.set()
		if self.captureThread.is_alive():
			self.captureThread.join(timeout=3)
		else:
			print("Capture thread is not alive, we are good!")

		# Change startstop button to start
		self.startstop["text"] = "Start"
		self.startstop["command"] = self.do_start
		self.startstop["fg"] = "green"

		# Enable region button
		self.region["state"] = "normal"

		# Enable spf and fps entries
		self.capSPF["state"] = "normal"
		self.outputFPS["state"] = "normal"
		self.cameraSelector["state"] = "normal"
		self.camMode["state"] = "normal"

		# Get FFMPEG from package
		ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()

		# Create video from images
		print("Creating video...")

		# Get all images in directory
		images = sorted(self.directory.glob("*.png"))

		# Create ffmpeg subprocess
		ffmpeg_sub = subprocess.Popen(
			[
				ffmpeg,
				"-y",  # Overwrite output file if it exists
				"-r", str(int(self.outputFPS.get())),  # Set video rate
				"-f", "image2pipe",	 # Input format
				"-i", "-",  # Input from stdin
				"-frames:v", str(len(images)),  # Set number of frames
				"-c:v", "libx264",  # Video codec
				"-pix_fmt", "yuv420p",  # Pixel format
				"-movflags", "+faststart",  # Fast start
				str(self.directory / f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.mp4")  # Output file
			],
			stdin=subprocess.PIPE
		)

		# Write images to ffmpeg stdin
		for image in images:
			with open(image, "rb") as f:
				ffmpeg_sub.stdin.write(f.read())

		# Close stdin
		ffmpeg_sub.stdin.close()

		# Wait for ffmpeg to finish
		ffmpeg_sub.wait()

		print("Done")

	def on_quit(self):
		if not self.stopEvent.is_set():
			self.do_stop()

		self.master.destroy()


if __name__ == "__main__":
	root = tk.Tk()
	app = ScreenTimelapseApp(master=root)
	app.mainloop()
