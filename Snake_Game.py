#!/usr/bin/env python
# coding: utf-8

# In[1]:


from turtle import Turtle,Screen
import time
import random
screen = Screen()

screen.setup(width=600, height=600)
screen.bgcolor('black')
screen.title('Snake Game')
screen.tracer(0)



starting_position = [(0,0), (-20,0), (-40,0)]
move_distance = 20
right = 0
up = 90 
left = 180
down = 270


class Snake:
  def __init__(self):
    self.segments = []
    self.create_snake()
    self.head = self.segments[0]
    
  def create_snake(self):
    for i in starting_position:
       self.add_segment(i)

  def add_segment(self, position):
    tim = Turtle('square')
    tim.color('white')
    tim.penup()
    tim.goto(position)
    self.segments.append(tim)

  

  def extend(self):
    self.add_segment(self.segments[-1].position())

  
  def move(self):
    for seg_num in range(len(self.segments)-1,0,-1):
      new_x = self.segments[seg_num -1].xcor()
      new_y = self.segments[seg_num -1].ycor()
      self.segments[seg_num].goto(new_x,new_y)
    self.segments[0].forward(move_distance)
  

  def up(self):
    if self.head.heading() != down:
      self.head.setheading(up)

  def down(self):
    if self.head.heading() != up:
      self.head.setheading(down)
    
  def left(self):
    if self.head.heading() != right:
     self.head.setheading(left)
    
  def right(self):
    if self.head.heading() != left:
      self.head.setheading(right)



class Food(Turtle):
  def __init__(self):
    super().__init__()
    self.shape('circle')
    self.penup()
    self.shapesize(stretch_wid=0.5, stretch_len=0.5)
    self.color('blue')
    self.speed("fastest")
    self.refresh()
    
  def refresh(self):
    random_x = random.randint(-280,280)
    random_y = random.randint(-280,280)
    self.goto(random_x,random_y)


              
class ScoreBoard(Turtle):
  def __init__(self):
    super().__init__()
    self.goto(0, 270)
    self.color('white')
    self.score = 0
    self.write(f'Score: {self.score}', align='center', font=('Courier', 20 , 'normal'))
    self.hideturtle()

  def score_increase(self):
    self.score += 1
    self.clear()
    self.write(f'Score: {self.score}', align='center', font=('Courier', 20 , 'normal'))

  def game_over(self):
    self.goto(0, 0)
    self.write('Game Over', align='center', font=('Courier', 20 , 'normal'))
    

snake = Snake()
food = Food()
scoreboard = ScoreBoard()

screen.listen()
screen.onkey(snake.up, "Up")
screen.onkey(snake.down, "Down")
screen.onkey(snake.left, "Left")
screen.onkey(snake.right, "Right")


game_is_on = True

while game_is_on:
  screen.update()
  time.sleep(0.1)
  snake.move()

  if snake.head.distance(food) < 15:
    snake.extend()
    scoreboard.score_increase()
    food.refresh()

  if snake.head.xcor() > 280 or snake.head.xcor() < -280 or snake.head.ycor() > 280 or snake.head.ycor() < -280:
    game_is_on = False
    scoreboard.game_over()

  for x in snake.segments:
    if x == snake.head:
      continue
    if x.distance(snake.head) < 10:
      game_is_on = False
      scoreboard.game_over()

