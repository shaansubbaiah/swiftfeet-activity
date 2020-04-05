# -*- coding: utf-8 -*-

# Copyright 2012 Daniel Drake
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import os
import logging

import gobject
gobject.threads_init()

import gtk
from gtk import gdk
import gst
import gio
import glib

from gettext import gettext as _

from sugar.activity import activity
from sugar.graphics.toolbarbox import ToolbarBox
from sugar.graphics.toolbutton import ToolButton
from sugar.activity.widgets import ActivityToolbarButton
from sugar.activity.widgets import StopButton

from videos import EXERCISES, DANCES

class PaddedVBox(gtk.VBox):
    __gtype_name__ = "PaddedVBox"

    def do_size_allocate(self, allocation):
        allocation.width -= 20
        allocation.height -= 20 
        allocation.x += 10
        allocation.y += 10
        gtk.VBox.do_size_allocate(self, allocation)

class VideoPlayer(gtk.EventBox):
    def __init__(self):
        super(VideoPlayer, self).__init__()
        self.unset_flags(gtk.DOUBLE_BUFFERED)
        self.set_flags(gtk.APP_PAINTABLE)

        self._sink = None
        self._xid = None
        self.connect('realize', self.__realize)

        # video
        self._vpipeline = gst.element_factory_make("playbin2", "vplayer")
        # audio (instructions)
        self._apipeline = gst.element_factory_make("playbin2", "aplayer")
        # music
        self._mpipeline = gst.element_factory_make("playbin2", "mplayer")

        bus = self._vpipeline.get_bus()
        bus.enable_sync_message_emission()
        bus.add_signal_watch()
        bus.connect('sync-message::element', self.__on_sync_message)
        bus.connect('message', self.__on_vmessage)

        bus = self._apipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self.__on_amessage)

        bus = self._mpipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self.__on_mmessage)

    def __on_sync_message(self, bus, message):
        if message.structure is None:
            return
        if message.structure.get_name() == 'prepare-xwindow-id':
            message.src.set_property('force-aspect-ratio', True)
            self._sink = message.src
            self._sink.set_xwindow_id(self._xid)

    def __on_vmessage(self, bus, message):
        t = message.type
        if t == gst.MESSAGE_EOS:
            self._vpipeline.seek_simple(gst.FORMAT_TIME, gst.SEEK_FLAG_FLUSH, 0)

    def __on_mmessage(self, bus, message):
        t = message.type
        if t == gst.MESSAGE_EOS:
            self._mpipeline.seek_simple(gst.FORMAT_TIME, gst.SEEK_FLAG_FLUSH, 0)

    def __on_amessage(self, bus, message):
        t = message.type
        if t != gst.MESSAGE_EOS:
            return

        self._apipeline.set_state(gst.STATE_NULL)

        uri = self._mpipeline.get_property('uri')
        if not uri:
            return

        # If music is not playing, its probably because we're on XO-1.75
        # without software mixing support (one sound at a time). Start
        # the music now.
        ret, state, pending = self._mpipeline.get_state()
        if state != gst.STATE_PLAYING:
            # Wait for apipeline to stop
            self._apipeline.get_state()

            # Need to reprogram URI for unknown reasons
            self._mpipeline.set_property('uri', uri)
            ret = self._mpipeline.set_state(gst.STATE_PLAYING)

    def __realize(self, widget):
        self._xid = self.window.xid

    def do_expose_event(self):
        if self._sink:
            self._sink.expose()
            return False
        else:
            return True

    def play(self, filename, music_name):
        if filename:
            path = os.path.join(activity.get_bundle_path(), "video", filename + ".ogg")
            gfile = gio.File(path=path)
            self._vpipeline.set_property('uri', gfile.get_uri())

        ret = self._vpipeline.set_state(gst.STATE_PLAYING)

        if filename:
            path = os.path.join(activity.get_bundle_path(), "audio", filename + ".ogg")
            gfile = gio.File(path=path)
            if gfile.query_exists():
                self._apipeline.set_property('uri', gfile.get_uri())
                self._apipeline.set_state(gst.STATE_PLAYING)

        self._mpipeline.set_property('uri', None)
        if music_name:
            path = os.path.join(activity.get_bundle_path(), "music", music_name + ".ogg")
            gfile = gio.File(path=path)
            if gfile.query_exists():
                # FIXME: XO-1.75 doesn't have software mixing at the moment
                # Only one sound can be played at the same time.
                # Work around this: wait for apipeline to start playing,
                # to make sure that the audio always beats the music in this
                # situation.
                # Then, if the mpipeline state change fails below, we start
                # the music in the EOS handler for apipeline.
                self._apipeline.get_state()
                self._mpipeline.set_property('uri', gfile.get_uri())
                self._mpipeline.set_state(gst.STATE_PLAYING)

    def stop(self):
        self._vpipeline.set_state(gst.STATE_NULL)
        self._apipeline.set_state(gst.STATE_NULL)
        self._mpipeline.set_state(gst.STATE_NULL)

class VideoButton(gtk.EventBox):
    def __init__(self, title, image_path):
        super(VideoButton, self).__init__()
        self.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#000000"))
        self.connect('realize', self._eventbox_realized)
        self.connect('enter-notify-event', self._eventbox_entered)
        self.connect('leave-notify-event', self._eventbox_left)

        self._image_path = image_path
        self._last_width = 0
        self._last_height = 0

        self._frame = gtk.Frame()
        self._frame.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#000000"))
        self.add(self._frame)
        self._frame.show()

        self._vbox = gtk.VBox()
        self._frame.add(self._vbox)
        self._vbox.show()

        self._image = gtk.Image()
        self._image.connect('size-allocate', self._image_size_allocated)
        self._vbox.pack_start(self._image, expand=True, fill=True, padding=5)
        self._image.show()

        self._title = gtk.Label(title)
        self._title.modify_fg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#FFFFFF"))
        self._vbox.pack_start(self._title, expand=False, padding=5)
        self._title.show()

    def _image_size_allocated(self, widget, allocation):
        if not self._image_path:
            return False
        if self._last_width == allocation.width and self._last_height == allocation.height:
            return False

        width = allocation.width
        self._last_width = width
        height = allocation.height
        self._last_height = height
        pixbuf = gdk.pixbuf_new_from_file_at_size(self._image_path, width, height)
        self._image.set_from_pixbuf(pixbuf)

    def _eventbox_entered(self, widget, event):
        self._frame.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#333333"))

    def _eventbox_left(self, widget, event):
        self._frame.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#000000"))

    def _eventbox_realized(self, widget):
        self.window.set_cursor(gdk.Cursor(gdk.HAND2))

class SwiftFeetActivity(activity.Activity):
    def __init__(self, handle):
        activity.Activity.__init__(self, handle)
        self._current_video_idx = None
        self.max_participants = 1

        # Set blackground as black
        self.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#000000"))

        if hasattr(self, '_event_box'):
            # for pre-0.96
            self._event_box.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#000000"))

        toolbar_box = ToolbarBox()
        activity_button = ActivityToolbarButton(self)
        toolbar_box.toolbar.insert(activity_button, 0)
        activity_button.show()

        self._exercise_button = ToolButton('fitness')
        self._exercise_button.set_tooltip(_("Excercises"))
        self._exercise_button.connect('clicked', self._index_clicked)
        self._exercise_button.set_sensitive(False)
        self._exercise_button.show()
        toolbar_box.toolbar.insert(self._exercise_button, -1)

        self._dance_button = ToolButton('dancer')
        self._dance_button.set_tooltip(_("Dances"))
        self._dance_button.connect('clicked', self._index_clicked)
        self._dance_button.show()
        toolbar_box.toolbar.insert(self._dance_button, -1)

        separator = gtk.SeparatorToolItem()
        toolbar_box.toolbar.insert(separator, -1)
        separator.show()

        self._prev_button = ToolButton('go-left')
        self._prev_button.set_tooltip(_("Previous exercise"))
        self._prev_button.connect('clicked', self._prev_clicked)
        self._prev_button.set_sensitive(False)
        self._prev_button.show()
        toolbar_box.toolbar.insert(self._prev_button, -1)

        self._next_button = ToolButton('go-right')
        self._next_button.set_tooltip(_("Next exercise"))
        self._next_button.connect('clicked', self._next_clicked)
        self._next_button.set_sensitive(False)
        self._next_button.show()
        toolbar_box.toolbar.insert(self._next_button, -1)

        separator = gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        separator.show()
        toolbar_box.toolbar.insert(separator, -1)

        tool = StopButton(self)
        toolbar_box.toolbar.insert(tool, -1)
        tool.show()

        self.set_toolbox(toolbar_box)
        toolbar_box.show()

        vbox = PaddedVBox()
        vbox.show()
        self.set_canvas(vbox)

        self._menu = gtk.Table(4, 5, True)
        self._menu.set_row_spacings(10)
        self._menu.set_col_spacings(10)
        vbox.pack_start(self._menu, expand=True, fill=True)
        self._menu.show()

        self._videos = EXERCISES
        self._generate_menu()

        self._video_title = gtk.Label()
        self._video_title.modify_fg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#FFFFFF"))
        vbox.pack_start(self._video_title, expand=False)

        self._video = VideoPlayer()
        vbox.pack_start(self._video, expand=True, fill=True, padding=10)
        self._video.realize()

        self._video_description = gtk.Label()
        self._video_description.set_line_wrap(True)
        self._video_description.modify_fg(gtk.STATE_NORMAL, gtk.gdk.color_parse("#FFFFFF"))
        vbox.pack_start(self._video_description, expand=False)

        # Try to fix description height to 3 lines so that it doesn't shift size while
        # changing videos.
        self._video_description.set_text("\n\n\n")
        size_req = self._video_description.size_request()
        self._video_description.set_size_request(-1, size_req[1])

    def _generate_menu(self):
        for child in self._menu.get_children():
            self._menu.remove(child)

        for (i, video) in enumerate(self._videos):
            path = os.path.join(activity.get_bundle_path(), "thumbnails", video[0] + ".png")
            button = VideoButton(video[1], path)
            button.connect('button_press_event', self.__menu_item_clicked, i)

            col = i % 5
            row = i / 5
            self._menu.attach(button, col, col + 1, row, row + 1)
            button.show_all()

    def _play_video(self, idx):
        video = self._videos[idx]
        self._menu.hide()
        self._video.show()
        self._video.stop()

        self._video_title.set_markup('<span size="x-large" weight="bold">' + glib.markup_escape_text(video[1]) + '</span>')
        self._video_title.show()

        if len(video) > 2:
            self._video_description.set_text(video[2].strip())
        else:
            self._video_description.set_text('')
        self._video_description.show()

        if len(video) > 3:
            music_name = video[3]
        else:
            music_name = None

        self._video.play(video[0], music_name)
        self._current_video_idx = idx
        self._dance_button.set_sensitive(True)
        self._exercise_button.set_sensitive(True)

        self._prev_button.set_sensitive(idx != 0)
        self._next_button.set_sensitive(idx != (len(self._videos) - 1))

    def _index_clicked(self, widget):
        self._video.stop()
        self._video.hide()
        self._next_button.set_sensitive(False)
        self._prev_button.set_sensitive(False)
        self._video_title.hide()
        self._video_description.hide()

        if widget == self._exercise_button:
            self._videos = EXERCISES
        else:
            self._videos = DANCES
        self._generate_menu()

        self._menu.show()
        self._exercise_button.set_sensitive(widget == self._dance_button)
        self._dance_button.set_sensitive(widget == self._exercise_button)

    def _next_clicked(self, widget):
        self._play_video(self._current_video_idx + 1)

    def _prev_clicked(self, widget):
        self._play_video(self._current_video_idx - 1)

    def __menu_item_clicked(self, widget, event, idx):
        logging.warning("CLICKED")
        self._play_video(idx)
