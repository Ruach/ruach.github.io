ROOT_DIR := $(CURDIR)
CHIRPY_DIR := $(ROOT_DIR)/chirpy
GH_PAGES_DIR := $(ROOT_DIR)/gh-pages
DEPLOY_DATE := $(shell date +'%Y-%m-%d %H:%M:%S')

.PHONY: build serve posts deploy clean_up 

build: chirpy gh-pages posts
	@cd $(CHIRPY_DIR) && bundle exec jekyll build

local: chirpy gh-pages posts
	@cd $(CHIRPY_DIR) && bundle exec jekyll serve 

chirpy: 
	@if [ ! -d "$(CHIRPY_DIR)" ]; then \
		git worktree add --guess-remote chirpy; \
		bundle install --gemfile=$(CHIRPY_DIR)/Gemfile \
	fi

gh-pages:
	@if [ ! -d "$(GH_PAGES_DIR)" ]; then \
		git worktree add --guess-remote gh-pages; \
	fi

posts:
	@if [ ! -d "$(CHIRPY_DIR)/_posts" ]; then \
		ln -s $(ROOT_DIR)/_posts $(CHIRPY_DIR)/; \
	fi


deploy: build
	@rm -rf $(GH_PAGES_DIR)/*
	@cp -r $(CHIRPY_DIR)/_site/* $(GH_PAGES_DIR)/
	@cd $(GH_PAGES_DIR) && git add --all
	@cd $(GH_PAGES_DIR) && git commit -m "Deployed on $(DEPLOY_DATE)"
	@cd $(GH_PAGES_DIR) && git push


