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

# This script takes screenshots of the screen and creates a timelapse pictures from them.
import pathlib
import datetime
import threading
import subprocess
import time

from mss import mss
import tkinter as tk
from PIL import Image
from static_ffmpeg import run
from pynput.mouse import Controller

VERSION = "0.1.0"


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
		self.capturing = False
		self.regionData = {"top": 0, "left": 0, "width": 0, "height": 0}
		self.captureThread = None
		self.directory = None

		self.create_widgets()

	def create_widgets(self):
		self.title = tk.Label(self, text=f"py-screen-timelapse v{VERSION}")
		self.title.pack(side="top")

		self.region = tk.Button(self, text="Region", command=self.set_region)
		self.region.pack(side="top")

		self.startstop = tk.Button(self, text="Start", command=self.do_start)
		self.startstop["fg"] = "green"
		# Disable startstop button until region is set
		self.startstop["state"] = "disabled"
		self.startstop.pack(side="top")

		self.spfText = tk.Label(self, text="Capture every n seconds:")
		self.spfText.pack(side="top")

		self.capSPF = tk.Entry(self)
		self.capSPF.insert(0, "1")  # Seconds per frame
		self.capSPF.pack(side="top")

		self.outFPSText = tk.Label(self, text="Output FPS:")
		self.outFPSText.pack(side="top")

		self.outputFPS = tk.Entry(self)
		self.outputFPS.insert(0, "60")  # Output FPS
		self.outputFPS.pack(side="top")

		self.capturedFrames = tk.Label(self, text="Captured frames: 0")
		self.capturedFrames.pack(side="bottom")

		self.quit = tk.Button(self, text="Quit", fg="red", command=self.on_quit)
		self.quit.pack(side="bottom")

	def set_region(self):
		# Specify region by clicking and dragging a rectangle on monitor (create undecorated window)
		x1, y1, x2, y2 = 0, 0, 0, 0
		left, top, right, bottom = 0, 0, 0, 0
		resizing = False
		text = None
		mouse = Controller()

		def on_click(event):
			nonlocal x1, y1
			if not resizing:
				x1, y1 = event.x, event.y
			else:
				x1, y1 = mouse.position

		def on_move(event):
			nonlocal x1, y1, x2, y2, resizing, left, top, right, bottom

			# If not resizing, get mouse position to reposition fakeRoot
			if not resizing:
				mX, mY = mouse.position
				fakeRoot.geometry(f"+{mX-x1}+{mY-y1}")
				left = mX-x1
				top = mY-y1
			else:
				# Otherwise, resize fakeRoot, minimum is 100x100
				x2, y2 = mouse.position
				width = max(x2-x1, 100)
				height = max(y2-y1, 100)
				fakeRoot.geometry(f"{width}x{height}+{x1}+{y1}")
				right = x1+width
				bottom = y1+height

		def finish():
			nonlocal x1, y1, x2, y2, resizing, left, top, right, bottom
			# Save region data
			self.regionData["left"] = left
			self.regionData["top"] = top

			# Width and height must be divisible by 2
			self.regionData["width"] = (right-left) // 2 * 2
			self.regionData["height"] = (bottom-top) // 2 * 2

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
		fakeRoot.geometry(f"+{screenWidth // 2 - 100}+{screenHeight // 2 - 100}")

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
		if self.capturing or self.regionData["width"] == 0 or self.regionData["height"] == 0:
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

		# Create new directory with current date under "./timelapses/" and start capturing
		self.directory = pathlib.Path("timelapses") / datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
		self.directory.mkdir(parents=True, exist_ok=True)

		def capture_loop():
			frame = 0
			self.capturing = True
			with mss() as sct:
				while self.capturing:
					sct_img = sct.grab(self.regionData)

					# Convert to PIL Image
					img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

					# Save image (number of frame as filename)
					img.save(self.directory / f"{frame}.png")
					frame += 1

					# Update capturedFrames label
					self.capturedFrames["text"] = f"Captured frames: {frame}"

					# Sleep for specified seconds per frame
					time.sleep(int(self.capSPF.get()))

		# Create capture thread
		self.captureThread = threading.Thread(target=capture_loop)
		print("Starting capture thread")
		self.captureThread.start()

	def do_stop(self):
		# Stop capturing
		if self.capturing:
			self.capturing = False
			self.captureThread.join()

			# Change startstop button to start
			self.startstop["text"] = "Start"
			self.startstop["command"] = self.do_start
			self.startstop["fg"] = "green"

			# Enable region button
			self.region["state"] = "normal"

			# Enable spf and fps entries
			self.capSPF["state"] = "normal"
			self.outputFPS["state"] = "normal"

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
					"-framerate", str(self.outputFPS.get()),  # Set framerate
					"-f", "image2pipe",  # Input format
					"-i", "-",  # Input from stdin
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
		if self.capturing:
			self.do_stop()

		self.master.destroy()


if __name__ == "__main__":
	root = tk.Tk()
	app = ScreenTimelapseApp(master=root)
	app.mainloop()
