# script to crop paleoclimate data to NYC 

library(terra)
library(sf)
library(dplyr)
library(purrr)
library(rnaturalearth)
library(ggplot2)
library(tidyterra)
library(magick)
library(gganimate)

# get New York State Shapefile
states <- ne_states(country = "united states of america", returnclass = "sf") %>% 
  filter(name_en == "New York") %>% 
  vect()

# read in paleoclimate data. this is processing data from local files
# and is not included in this repository
paleo_dirs <- list.dirs("/Users/connorfrench/Dropbox/Old_Mac/climate-data/paleoclim_late_pleistocene", recursive = FALSE) 

paleo_files <- paleo_dirs %>% 
  map_chr(\(x) list.files(x, pattern = "bio_1.tif$", full.names = TRUE))

names(paleo_files) <- paste0("tp", basename(paleo_dirs))

# read in the paleoclimate data
paleo_data <- paleo_files %>% 
  map(terra::rast) %>% 
  map(terra::project, crs(states)) %>%
  map(terra::crop, states) %>% 
  map(terra::mask, states)


min_max <- paleo_data %>% 
  map(terra::minmax)


# 1. raster gif -----------------------------------------------------------

plot_temp <- function(raster, states) {
  ggplot() +
    geom_spatraster(data = raster) +
    theme_void() +
    geom_spatvector(data = states, fill = "transparent") +
    # set the min and max values of the fill scale
    scale_fill_whitebox_c("muted", limits = c(-226, 125)) +
    annotate("text", x = -73.94773270154228 - 2.1, y = 40.82027056305716 - 0.23, label = "You are here", vjust = -1, hjust = 0.5, size = 10) +
    annotate("segment", x = -73.94773270154228 - 1, y = 40.82027056305716, xend = -73.94773270154228, yend = 40.82027056305716, arrow = arrow(length = unit(0.3, "cm"))) +
  theme(legend.position = "none")
}

# loop through the rasters and make plots of each
paleo_plots <- paleo_data %>% 
  map(plot_temp, states) 

# reverse the order of the plots
paleo_plots <- rev(paleo_plots)

# convert to a gif
images <- map(paleo_plots, function(plot) {
  # Save each plot to a temporary file
  plot_file <- tempfile(fileext = ".png")
  ggsave(plot_file, plot, width = 10, height = 8)
  # Read the image
  magick::image_read(plot_file)
})

# Create an animated GIF
animated_gif <- magick::image_animate(magick::image_join(images), fps = 2)
magick::image_write(animated_gif, "images/temperature_change.gif")


# 2. animated line plot ---------------------------------------------------

# get the mean temperature for each raster
mean_temp <- paleo_data %>% 
  map_dfr(\(x) global(x, mean, na.rm = TRUE), .id = "raster") %>% 
  mutate(time = c(0, 3, 6, 12, 14, 16, 21),
         rev_time = -time)

animated_line_plot <- ggplot(mean_temp, aes(x = time, y = mean / 10)) +
  geom_line(linewidth = 2) +
  geom_point(aes(group = 1), color = "red", size = 8) +
  labs(x = "Time (thousands of years ago)", y = "Mean temperature (°C)") +
  theme_bw() +
  theme(
    legend.position = "none",
    axis.title = element_text(size = 28),
    axis.text = element_text(size = 22)
    ) +
  transition_reveal(rev_time) +
  ease_aes('linear') +
  enter_fade()


anim_save("images/temp_line_plot.gif", animation = animate(animated_line_plot, fps = 2, nframes = 7, width = 10, height = 8, units = "in", res = 300, bg = "transparent"))


