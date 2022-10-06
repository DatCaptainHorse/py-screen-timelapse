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
from mss import mss
import tkinter as tk
from PIL import Image
from pynput.mouse import Controller

VERSION = "0.1.0"


class ScreenTimelapseApp(tk.Frame):
	def __init__(self, master=None):
		super().__init__(master)
		self.master = master
		self.pack()

		self.quit = None
		self.region = None
		self.start = None
		self.stop = None
		self.title = None
		self.capFPS = None
		self.capturing = False
		self.regionData = {"top": 0, "left": 0, "width": 0, "height": 0}
		self.captureThread = None
		self.directory = None

		self.create_widgets()

	def create_widgets(self):
		self.title = tk.Label(self, text=f"py-screen-timelapse v{VERSION}")
		self.title.pack(side="top")

		self.quit = tk.Button(self, text="Quit", fg="red", command=self.master.destroy)
		self.quit.pack(side="bottom")

		self.region = tk.Button(self, text="Region", command=self.set_region)
		self.region.pack(side="bottom")

		self.start = tk.Button(self, text="Start", command=self.do_start)
		self.start.pack(side="top")

		self.stop = tk.Button(self, text="Stop", command=self.do_stop)
		self.stop.pack(side="top")

		self.capFPS = tk.Entry(self)
		self.capFPS.insert(0, "30")
		self.capFPS.pack(side="top")

	def set_region(self):
		# Specify region by clicking and dragging a rectangle on monitor (create undecorated window)
		x1, y1, x2, y2 = 0, 0, 0, 0
		resizing = False
		text = None
		mouse = Controller()

		def on_click(event):
			nonlocal x1, y1
			x1, y1 = event.x, event.y

		def on_move(event):
			nonlocal x1, y1, x2, y2, resizing

			# If not resizing, get mouse position to reposition fakeRoot
			if not resizing:
				mX, mY = mouse.position
				fakeRoot.geometry(f"+{mX - x1}+{mY - y1}")
			else:
				# Otherwise, resize fakeRoot
				x2, y2 = mouse.position
				fakeRoot.geometry(f"{x2 - x1}x{y2 - y1}")

		def finish():
			nonlocal x1, y1, x2, y2, resizing
			# Save region data
			self.regionData["left"] = x1
			self.regionData["top"] = y1
			self.regionData["width"] = x2 - x1
			self.regionData["height"] = y2 - y1
			print(f"Region set to {self.regionData}")
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

		# Create capture thread
		self.captureThread = threading.Thread(target=capture_loop)
		print("Starting capture thread")
		self.captureThread.start()

	def do_stop(self):
		# Stop capturing
		if self.capturing:
			self.capturing = False
			self.captureThread.join()

			# Find ffmpeg, PATH first then in current directory
			ffmpeg = pathlib.Path("ffmpeg")
			# Check if ffmpeg is in PATH
			if not ffmpeg.exists():
				ffmpeg = pathlib.Path("ffmpeg.exe")
			if not ffmpeg.exists():
				print("FFMPEG not found, skipping video creation")
				return

			# Create video from images
			print("Creating video...")

			# Get all images in directory
			images = sorted(self.directory.glob("*.png"))

			# Create ffmpeg subprocess
			ffmpeg_sub = subprocess.Popen(
				[
					ffmpeg,
					"-y", # Overwrite output file if it exists
					"-r", self.capFPS.get(), # FPS
					"-i", str(self.directory / "%d.png"), # Input images
					"-c:v", "libx264", # Video codec
					"-pix_fmt", "yuv420p", # Pixel format
					str(self.directory / f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.mp4") # Output file
				],
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE
			)

			# Wait for ffmpeg to finish
			ffmpeg_sub.wait()

			print("Done")


if __name__ == "__main__":
	root = tk.Tk()
	app = ScreenTimelapseApp(master=root)
	app.mainloop()
