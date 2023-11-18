# Slightly modified https://github.com/willnorris/willnorris.com/blob/jekyll/src/_plugins/symlink_watcher.rb

require "find"
require "jekyll-watch"

module Jekyll
  module Watcher
    SYM_LINKED_FILES = ["_posts"].freeze
    ADDITIONAL_FILES = [].freeze
    def build_listener_with_symlinks(site, options)
      src = options["source"]
      dirs = [src]

      SYM_LINKED_FILES.each do |sym_linked_file|
        Find.find(sym_linked_file).each do |f|
          dirs << f if File.directory?(f) && File.symlink?(f)
        end
      end

      dirs += ADDITIONAL_FILES

      require "listen"
      Listen.to(
        *dirs,
        :ignore => listen_ignore_paths(options),
        :force_polling => options['force_polling'],
        &(listen_handler(site))
      )
    end

    alias_method :build_listener_without_symlinks, :build_listener
    alias_method :build_listener, :build_listener_with_symlinks
  end
end

